"""
The baseline system the plan asks for: a simple, naive rule, not an
LLM, not optimization -- exactly what a team might have shipped before
building any of this. It exists purely as a comparison point for
evaluation/run_baseline_vs_ai_eval.py.

Per the plan's own example:
    IF supplier delayed -> use backup supplier

Deliberately crude on purpose:
  - Picks the FIRST other approved supplier available, no reliability
    score, no cost comparison, no policy lookup.
  - Assigns a flat, pessimistic notional cost and delay, since a real
    naive system wouldn't negotiate or optimize either.
  - Has no answer at all for incident types outside shipment/supplier
    delays -- it just "waits" (does nothing), which is exactly the kind
    of gap the full AI system is supposed to close.
"""
from datetime import datetime, timedelta, timezone

from app.models.enums import IncidentType, ShipmentStatus
from app.models.master_data import Supplier
from app.models.operations import Shipment

# Deliberately pessimistic flat assumptions -- a naive system has no way to
# actually know the real cost/delay of switching suppliers on the fly.
BASELINE_SWITCH_COST = 15000.0
BASELINE_SWITCH_DELAY_DAYS = 3


def apply_baseline_rule(db, company_id, incident) -> dict:
    """
    Returns a result dict shaped similarly to the AI system's action
    result, so the eval harness can measure both the same way:
    {"action_taken": str, "estimated_cost": float, "expected_delay_days": int, "resolved": bool}
    """
    if incident.type in (IncidentType.SHIPMENT_DELAY, IncidentType.SUPPLIER_DELAY) and incident.shipment_id:
        shipment = db.get(Shipment, incident.shipment_id)
        if shipment is None:
            return {"action_taken": "none", "estimated_cost": None, "expected_delay_days": None, "resolved": False}

        backup = (
            db.query(Supplier)
            .filter(Supplier.company_id == company_id, Supplier.id != shipment.supplier_id, Supplier.is_approved == True)  # noqa: E712
            .first()
        )
        if backup is None:
            return {"action_taken": "none", "estimated_cost": None, "expected_delay_days": None, "resolved": False}

        shipment.status = ShipmentStatus.CANCELLED
        new_shipment = Shipment(
            company_id=company_id, supplier_id=backup.id, product_id=shipment.product_id,
            warehouse_id=shipment.warehouse_id, order_id=shipment.order_id, quantity=shipment.quantity,
            status=ShipmentStatus.SCHEDULED,
            expected_delivery=datetime.now(timezone.utc) + timedelta(days=BASELINE_SWITCH_DELAY_DAYS),
            delay_days=0,
        )
        db.add(new_shipment)
        db.commit()
        return {
            "action_taken": "use_backup_supplier", "estimated_cost": BASELINE_SWITCH_COST,
            "expected_delay_days": BASELINE_SWITCH_DELAY_DAYS, "resolved": True,
        }

    # No rule for inventory_shortage, demand_spike, or logistics_disruption --
    # this gap is intentional; it's what the full pipeline is meant to cover.
    return {"action_taken": "none (no baseline rule for this incident type)", "estimated_cost": None,
            "expected_delay_days": None, "resolved": False}