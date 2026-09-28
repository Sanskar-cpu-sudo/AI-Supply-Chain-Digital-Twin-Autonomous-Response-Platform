"""
Executes an APPROVED recommendation. Per the plan: "The actual action
should be deterministic code, not an LLM improvising database changes."
There is no LLM anywhere in this file.

Each handler:
  1. Captures a "before" snapshot of the metrics Phase 20's Verification
     Agent will need to check against (inventory level, orders at risk).
  2. Makes the actual, real database change.
  3. Returns a result dict describing exactly what changed.

The Action row itself enforces "only once" at the DB level too --
Action.recommendation_id has a unique constraint (Phase 2), so even if
this function were somehow called twice for the same recommendation,
the second commit would fail rather than silently double-executing.
"""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.action import Action
from app.models.audit_log import AuditLog
from app.models.enums import ActionStatus, ActorType, RecommendationStatus, ShipmentStatus, VerificationResult
from app.models.incident import Incident
from app.models.operations import Shipment
from app.models.recommendation import Recommendation
from app.services.metrics_snapshot import snapshot_metrics


class ActionError(Exception):
    """Raised for any reason an action cannot be executed -- caller (the
    route) should surface this as a 4xx, not a 500."""


def _find_chosen_option_data(recommendation: Recommendation) -> dict:
    """The full option dict (rationale, evidence, execution_data) for
    whichever option was chosen -- see recommendation_service.py's fix
    for why options_considered stores more than just the score."""
    for option in recommendation.options_considered:
        if option.get("option") == recommendation.option_chosen:
            return option
    return {}


def _execute_wait(db, company_id, incident, recommendation, option_data) -> dict:
    return {"note": "No action taken -- accepted the delay/impact as-is, per the approved 'wait' option."}


def _execute_expedite_shipment(db, company_id, incident, recommendation, option_data) -> dict:
    if incident.shipment_id is None:
        raise ActionError("expedite_shipment requires the incident to have a linked shipment_id, but it has none.")

    shipment = db.get(Shipment, incident.shipment_id)
    if shipment is None:
        raise ActionError(f"Linked shipment {incident.shipment_id} no longer exists.")

    old_expected = shipment.expected_delivery
    new_expected = datetime.now(timezone.utc) + timedelta(days=recommendation.expected_delay_days or 0)
    shipment.expected_delivery = new_expected
    shipment.status = ShipmentStatus.IN_TRANSIT
    shipment.delay_days = 0

    return {
        "shipment_id": str(shipment.id),
        "old_expected_delivery": old_expected.isoformat(),
        "new_expected_delivery": new_expected.isoformat(),
        "new_status": shipment.status.value,
    }


def _execute_alternate_shipping_route(db, company_id, incident, recommendation, option_data) -> dict:
    if incident.shipment_id is None:
        raise ActionError("alternate_shipping_route requires the incident to have a linked shipment_id, but it has none.")

    shipment = db.get(Shipment, incident.shipment_id)
    if shipment is None:
        raise ActionError(f"Linked shipment {incident.shipment_id} no longer exists.")

    old_expected = shipment.expected_delivery
    new_expected = datetime.now(timezone.utc) + timedelta(days=recommendation.expected_delay_days or 0)
    shipment.expected_delivery = new_expected
    shipment.status = ShipmentStatus.IN_TRANSIT
    shipment.delay_days = 0

    return {
        "shipment_id": str(shipment.id),
        "old_expected_delivery": old_expected.isoformat(),
        "new_expected_delivery": new_expected.isoformat(),
        "note": "Re-routed via alternate shipping method.",
    }


def _execute_use_backup_supplier(db, company_id, incident, recommendation, option_data) -> dict:
    target_supplier_id = option_data.get("execution_data", {}).get("target_supplier_id")
    if not target_supplier_id:
        raise ActionError(
            "use_backup_supplier requires execution_data.target_supplier_id, but the Decision "
            "Agent's option did not include one. Cannot execute without a real supplier to switch to."
        )
    try:
        target_supplier_uuid = uuid.UUID(str(target_supplier_id))
    except ValueError:
        raise ActionError(f"target_supplier_id '{target_supplier_id}' is not a valid id.")

    if incident.shipment_id is None:
        raise ActionError("use_backup_supplier requires the incident to have a linked shipment_id to replace.")
    old_shipment = db.get(Shipment, incident.shipment_id)
    if old_shipment is None:
        raise ActionError(f"Linked shipment {incident.shipment_id} no longer exists.")

    old_shipment.status = ShipmentStatus.CANCELLED

    new_shipment = Shipment(
        company_id=company_id,
        supplier_id=target_supplier_uuid,
        product_id=old_shipment.product_id,
        warehouse_id=old_shipment.warehouse_id,
        order_id=old_shipment.order_id,
        quantity=old_shipment.quantity,
        status=ShipmentStatus.SCHEDULED,
        expected_delivery=datetime.now(timezone.utc) + timedelta(days=recommendation.expected_delay_days or 0),
        delay_days=0,
    )
    db.add(new_shipment)
    db.flush()

    return {
        "cancelled_shipment_id": str(old_shipment.id),
        "new_shipment_id": str(new_shipment.id),
        "new_supplier_id": str(target_supplier_uuid),
        "expected_delivery": new_shipment.expected_delivery.isoformat(),
    }


def _execute_split_shipment(db, company_id, incident, recommendation, option_data) -> dict:
    split_quantity = option_data.get("execution_data", {}).get("split_quantity")
    if not split_quantity or split_quantity <= 0:
        raise ActionError(
            "split_shipment requires execution_data.split_quantity (a positive int), but none was provided."
        )
    if incident.shipment_id is None:
        raise ActionError("split_shipment requires the incident to have a linked shipment_id to split.")

    original = db.get(Shipment, incident.shipment_id)
    if original is None:
        raise ActionError(f"Linked shipment {incident.shipment_id} no longer exists.")
    if split_quantity >= original.quantity:
        raise ActionError(
            f"split_quantity ({split_quantity}) must be less than the original shipment's "
            f"quantity ({original.quantity}) -- otherwise there's nothing left to split off."
        )

    remaining_quantity = original.quantity - split_quantity
    original.quantity = split_quantity
    original.status = ShipmentStatus.IN_TRANSIT

    follow_up = Shipment(
        company_id=company_id,
        supplier_id=original.supplier_id,
        product_id=original.product_id,
        warehouse_id=original.warehouse_id,
        order_id=original.order_id,
        quantity=remaining_quantity,
        status=ShipmentStatus.SCHEDULED,
        expected_delivery=original.expected_delivery + timedelta(days=7),  # arbitrary later batch; a real
        # system would source this from supplier lead time data via a tool call in Phase 15
        delay_days=0,
    )
    db.add(follow_up)
    db.flush()

    return {
        "original_shipment_id": str(original.id),
        "original_shipment_new_quantity": split_quantity,
        "follow_up_shipment_id": str(follow_up.id),
        "follow_up_quantity": remaining_quantity,
    }


ACTION_HANDLERS = {
    "wait": _execute_wait,
    "expedite_shipment": _execute_expedite_shipment,
    "alternate_shipping_route": _execute_alternate_shipping_route,
    "use_backup_supplier": _execute_use_backup_supplier,
    "split_shipment": _execute_split_shipment,
}


def execute_action(db: Session, company_id, recommendation: Recommendation) -> Action:
    """
    Executes recommendation.option_chosen via its deterministic handler.
    Raises ActionError (not a bare exception) for anything that should
    surface as a clean 4xx to the caller -- missing execution_data,
    already-executed, not approved, etc.
    """
    if recommendation.status != RecommendationStatus.APPROVED:
        raise ActionError(
            f"Recommendation is '{recommendation.status.value}', not APPROVED -- cannot execute an "
            f"action for a recommendation that hasn't been approved by a human."
        )

    existing = db.query(Action).filter(Action.recommendation_id == recommendation.id).first()
    if existing is not None:
        raise ActionError(f"An action ({existing.id}) already exists for this recommendation -- cannot execute twice.")

    incident = db.get(Incident, recommendation.incident_id)
    handler = ACTION_HANDLERS.get(recommendation.option_chosen)
    if handler is None:
        raise ActionError(f"No execution handler registered for option '{recommendation.option_chosen}'.")

    option_data = _find_chosen_option_data(recommendation)
    before_snapshot = snapshot_metrics(db, company_id, incident)

    action = Action(
        company_id=company_id,
        incident_id=incident.id,
        recommendation_id=recommendation.id,
        action_type=recommendation.option_chosen,
        status=ActionStatus.EXECUTING,
        verification_before=before_snapshot,
        verification_result=VerificationResult.PENDING,
    )
    db.add(action)
    db.flush()

    try:
        result = handler(db, company_id, incident, recommendation, option_data)
    except ActionError:
        action.status = ActionStatus.FAILED
        action.result = {"error": "action handler raised ActionError -- see audit log"}
        db.commit()
        raise
    except Exception as e:  # noqa: BLE001 -- any unexpected DB/data issue must not crash the request
        action.status = ActionStatus.FAILED
        action.result = {"error": f"Unexpected error during execution: {e}"}
        db.commit()
        raise ActionError(f"Action execution failed unexpectedly: {e}")

    action.status = ActionStatus.COMPLETED
    action.executed_at = datetime.now(timezone.utc)
    action.result = result

    db.add(
        AuditLog(
            company_id=company_id,
            incident_id=incident.id,
            actor_type=ActorType.SYSTEM,
            event_type="action_executed",
            message=f"Action '{recommendation.option_chosen}' executed successfully.",
            meta={"action_id": str(action.id), "result": result},
        )
    )
    db.commit()
    db.refresh(action)
    return action