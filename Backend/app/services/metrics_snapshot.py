"""
Captures the specific metrics relevant to an incident's type -- used
identically for the 'before' snapshot (captured right before Phase 19
executes an action) and the 'after' snapshot (captured by Phase 20's
verification). Using the exact same function for both means there's no
risk of the two ever measuring slightly different things.
"""
from sqlalchemy.orm import Session

from app.models.incident import Incident
from app.models.operations import Inventory, Order, Shipment


def snapshot_metrics(db: Session, company_id, incident: Incident) -> dict:
    """
    Scoped to whatever entities this incident actually touches -- an
    inventory incident cares about stock levels, a shipment incident
    cares about orders at risk for that product, etc. Returns whatever
    is available; missing entities just get omitted rather than raising.
    """
    snapshot = {}

    if incident.product_id and incident.warehouse_id:
        inv = (
            db.query(Inventory)
            .filter(
                Inventory.company_id == company_id,
                Inventory.product_id == incident.product_id,
                Inventory.warehouse_id == incident.warehouse_id,
            )
            .first()
        )
        if inv:
            snapshot["inventory_quantity_on_hand"] = inv.quantity_on_hand
            snapshot["inventory_reorder_point"] = inv.reorder_point  # lets verification tell
            # "still below reorder point" apart from "fully recovered", not just "went up at all"

    if incident.product_id:
        orders_at_risk = (
            db.query(Order)
            .filter(
                Order.company_id == company_id,
                Order.product_id == incident.product_id,
                Order.status.in_(["pending", "at_risk"]),
            )
            .count()
        )
        snapshot["orders_at_risk_count"] = orders_at_risk

    if incident.shipment_id:
        shipment = db.get(Shipment, incident.shipment_id)
        if shipment:
            snapshot["shipment_status"] = shipment.status.value
            snapshot["shipment_delay_days"] = shipment.delay_days

    return snapshot