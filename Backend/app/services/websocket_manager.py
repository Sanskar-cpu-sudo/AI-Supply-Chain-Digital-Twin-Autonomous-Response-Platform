"""
Tracks active WebSocket connections, scoped per company -- the same
multi-tenant discipline as every REST endpoint in this app: a Contoso
connection must never receive an Acme broadcast.

Kept deliberately simple (in-memory dict) for a single-process deployment.
If this ever runs behind multiple backend processes/instances, broadcasts
would need to go through a shared pub/sub layer (e.g. Redis, which is
already in this project's stack) instead of an in-memory dict, since one
process's dict has no way to reach a connection held open by another.
"""
import json

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self._connections: dict[str, set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, company_id: str):
        await websocket.accept()
        self._connections.setdefault(company_id, set()).add(websocket)

    def disconnect(self, websocket: WebSocket, company_id: str):
        connections = self._connections.get(company_id)
        if connections is not None:
            connections.discard(websocket)
            if not connections:
                del self._connections[company_id]

    async def broadcast_to_company(self, company_id: str, message: dict):
        """
        Sends `message` to every connection for this company. Silently
        drops connections that fail to send (client disconnected without
        a clean close) rather than letting one dead socket break the
        broadcast to everyone else.
        """
        connections = self._connections.get(company_id, set())
        dead = []
        for ws in connections:
            try:
                await ws.send_text(json.dumps(message, default=str))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws, company_id)

    def connection_count(self, company_id: str) -> int:
        return len(self._connections.get(company_id, set()))


manager = ConnectionManager()