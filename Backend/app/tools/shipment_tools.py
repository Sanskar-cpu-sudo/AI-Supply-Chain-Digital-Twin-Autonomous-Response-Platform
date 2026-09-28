"""
Raw tool functions the Investigation Agent (Phase 12) will call. Kept as
plain functions here (not yet wrapped as LangChain @tool objects) so they
can be unit-tested directly against the DB without needing an LLM at all
-- see app/tools/registry.py for the LangChain-wrapped versions.

Every function is company-scoped and NEVER raises on a bad id -- it
returns a structured {"error": ...} dict instead, because a raised
exception would crash the agent's graph execution rather than letting
the agent see the failure and decide what to do next (e.g. abstain).
"""
import uuid

from sqlalchemy.orm import Session

from app.models.operations import Shipment


def get_shipment(db: Session, company_id, shipment_id: str) -> dict:
    """Fetch full details of a single shipment by id."""
    try:
        shipment_uuid = uuid.UUID(str(shipment_id))
    except ValueError:
        return {"error": f"'{shipment_id}' is not a valid shipment id"}

    shipment = (
        db.query(Shipment)
        .filter(Shipment.id == shipment_uuid, Shipment.company_id == company_id)
        .first()
    )
    if shipment is None:
        return {"error": f"No shipment found with id {shipment_id}"}

    return {
        "id": str(shipment.id),
        "supplier_id": str(shipment.supplier_id),
        "product_id": str(shipment.product_id),
        "warehouse_id": str(shipment.warehouse_id),
        "order_id": str(shipment.order_id) if shipment.order_id else None,
        "quantity": shipment.quantity,
        "status": shipment.status.value,
        "expected_delivery": shipment.expected_delivery.isoformat(),
        "actual_delivery": shipment.actual_delivery.isoformat() if shipment.actual_delivery else None,
        "delay_days": shipment.delay_days,
    }