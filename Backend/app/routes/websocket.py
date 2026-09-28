"""
WebSocket endpoint for real-time incident notifications.

Auth note: browsers' native WebSocket API cannot set an Authorization
header on the handshake request, so the JWT is passed as a query param
instead (?token=...) and decoded manually here -- this is the standard
workaround, not a security shortcut; the token is validated exactly the
same way get_current_user validates it for REST requests.
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from jose import JWTError

from app.database.session import SessionLocal
from app.models.company import User
from app.services.auth_service import decode_access_token
from app.services.websocket_manager import manager

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/incidents")
async def incidents_websocket(websocket: WebSocket, token: str):
    db = SessionLocal()
    try:
        payload = decode_access_token(token)
        user_id = payload.get("sub")
        user = db.get(User, user_id) if user_id else None
        if user is None or not user.is_active:
            await websocket.close(code=1008)  # policy violation
            return
        company_id = str(user.company_id)
    except JWTError:
        await websocket.close(code=1008)
        return
    finally:
        db.close()

    await manager.connect(websocket, company_id)
    try:
        while True:
            # This endpoint is push-only (server -> client). We still need
            # to await something to detect a client disconnect -- there is
            # nothing meaningful to do with received text, so it's ignored.
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, company_id)