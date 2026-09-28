from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models.company import User
from app.monitoring.rules import run_all_checks
from app.services.deps import get_current_user
from app.services.websocket_manager import manager

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


def _incident_broadcast_payload(incident) -> dict:
    """Matches the plan's own example: 'New Critical Incident, Shipment
    #101, 4-day delay, 1,200 orders affected' -- enough detail for the
    dashboard to render a toast/banner without a follow-up GET."""
    return {
        "event": "incident_created",
        "incident": {
            "id": str(incident.id),
            "type": incident.type.value,
            "severity": incident.severity.value,
            "description": incident.description,
            "shipment_id": str(incident.shipment_id) if incident.shipment_id else None,
            "created_at": incident.created_at.isoformat(),
        },
    }


@router.post("/run")
async def run_monitoring(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Runs the monitoring pass (Phase 9, unchanged, still fully synchronous)
    and, for each newly created incident, broadcasts it over WebSocket to
    every connection for this company (Phase 22). The synchronous
    monitoring logic and the async broadcast are deliberately kept
    separate -- monitoring doesn't need to know WebSockets exist.
    """
    result = run_all_checks(db, current_user.company_id)
    created_incidents = result.pop("created_incidents")  # raw ORM objects -- not JSON-safe, must not go in the response

    for incident in created_incidents:
        await manager.broadcast_to_company(str(current_user.company_id), _incident_broadcast_payload(incident))

    return result