"""
Compares an Action's 'before' snapshot against a freshly-computed 'after'
snapshot (same snapshot_metrics function for both). Success/failure is
determined by deterministic rules, not an LLM.

Phase 21: on failure, the incident either loops back to OPEN for a fresh
investigate -> recommend -> approve -> execute -> verify cycle (up to
MAX_REINVESTIGATIONS times), or escalates to human review once that
limit is exhausted.
"""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.agents.llm_client import get_llm
from app.models.action import Action
from app.models.audit_log import AuditLog
from app.models.enums import ActionStatus, ActorType, IncidentStatus, VerificationResult
from app.models.incident import Incident
from app.prompts.verification_prompt import build_verification_explanation_prompt
from app.services.metrics_snapshot import snapshot_metrics

MAX_REINVESTIGATIONS = 2  # per the plan: "Maximum 2 re-investigations. After that: HUMAN ESCALATION REQUIRED."


class VerificationError(Exception):
    pass


def determine_success(before: dict, after: dict) -> tuple[bool, str]:
    signals = []

    if "inventory_quantity_on_hand" in before and "inventory_quantity_on_hand" in after:
        before_qty, after_qty = before["inventory_quantity_on_hand"], after["inventory_quantity_on_hand"]
        after_reorder_point = after.get("inventory_reorder_point")
        if after_reorder_point is not None and after_qty >= after_reorder_point:
            signals.append(("inventory", 1, f"inventory recovered to {after_qty} units (at/above reorder point {after_reorder_point})"))
        elif after_qty < before_qty:
            signals.append(("inventory", -1, f"inventory dropped from {before_qty} to {after_qty} units"))
        elif after_qty > before_qty:
            signals.append(("inventory", 0, f"inventory improved from {before_qty} to {after_qty} but still below reorder point"))
        else:
            signals.append(("inventory", 0, f"inventory unchanged at {after_qty} units"))

    if "orders_at_risk_count" in before and "orders_at_risk_count" in after:
        before_count, after_count = before["orders_at_risk_count"], after["orders_at_risk_count"]
        if after_count < before_count:
            signals.append(("orders_at_risk", 1, f"orders at risk dropped from {before_count} to {after_count}"))
        elif after_count > before_count:
            signals.append(("orders_at_risk", -1, f"orders at risk increased from {before_count} to {after_count}"))
        else:
            signals.append(("orders_at_risk", 0, f"orders at risk unchanged at {after_count}"))

    if "shipment_status" in before and "shipment_status" in after:
        before_status, after_status = before["shipment_status"], after["shipment_status"]
        if before_status == "delayed" and after_status != "delayed":
            signals.append(("shipment_status", 1, f"shipment status changed from delayed to {after_status}"))
        elif before_status != "delayed" and after_status == "delayed":
            signals.append(("shipment_status", -1, "shipment status regressed to delayed"))
        else:
            signals.append(("shipment_status", 0, f"shipment status unchanged ({after_status})"))

    if "shipment_delay_days" in before and "shipment_delay_days" in after:
        before_delay, after_delay = before["shipment_delay_days"], after["shipment_delay_days"]
        if after_delay < before_delay:
            signals.append(("shipment_delay_days", 1, f"delay reduced from {before_delay} to {after_delay} days"))
        elif after_delay > before_delay:
            signals.append(("shipment_delay_days", -1, f"delay increased from {before_delay} to {after_delay} days"))
        else:
            signals.append(("shipment_delay_days", 0, f"delay unchanged at {after_delay} days"))

    if not signals:
        return False, "No measurable metrics were available to compare before/after -- cannot verify."

    any_worse = any(score == -1 for _, score, _ in signals)
    any_improved = any(score == 1 for _, score, _ in signals)
    success = any_improved and not any_worse
    reason = "; ".join(detail for _, _, detail in signals)
    return success, reason


def generate_verification_explanation(llm, incident, action, before, after, success) -> str:
    prompt = build_verification_explanation_prompt(incident, action, before, after, success)
    response = llm.invoke(prompt)
    return response.content.strip()


def verify_action(db: Session, company_id, action: Action) -> Action:
    if action.status != ActionStatus.COMPLETED:
        raise VerificationError(f"Action is '{action.status.value}', not COMPLETED -- cannot verify.")
    if action.verification_result != VerificationResult.PENDING:
        raise VerificationError(f"Action was already verified (result: '{action.verification_result.value}').")

    incident = db.get(Incident, action.incident_id)
    after_snapshot = snapshot_metrics(db, company_id, incident)
    success, deterministic_reason = determine_success(action.verification_before or {}, after_snapshot)

    try:
        llm = get_llm(temperature=0.3)
        explanation = generate_verification_explanation(llm, incident, action, action.verification_before or {}, after_snapshot, success)
    except Exception:
        explanation = deterministic_reason

    action.verification_after = after_snapshot
    action.verification_result = VerificationResult.SUCCESS if success else VerificationResult.FAILED
    action.verification_reason = explanation

    escalation_note = None
    if success:
        incident.status = IncidentStatus.RESOLVED
        incident.resolved_at = datetime.now(timezone.utc)
    else:
        if incident.reinvestigation_count < MAX_REINVESTIGATIONS:
            incident.reinvestigation_count += 1
            incident.status = IncidentStatus.OPEN  # loop back: POST /investigate runs a fresh cycle
            escalation_note = (
                f"Verification failed. Re-investigation {incident.reinvestigation_count}/{MAX_REINVESTIGATIONS} "
                f"triggered -- incident reset to OPEN for a fresh investigate -> recommend -> approve -> "
                f"execute -> verify cycle."
            )
        else:
            incident.status = IncidentStatus.ESCALATED
            escalation_note = (
                f"Verification failed after {incident.reinvestigation_count} re-investigation attempts "
                f"(limit reached). HUMAN ESCALATION REQUIRED -- automatic retries exhausted."
            )

    db.add(AuditLog(company_id=company_id, incident_id=incident.id, actor_type=ActorType.SYSTEM,
                     event_type="verification_completed",
                     message=f"Verification {'succeeded' if success else 'failed'}: {explanation}" + (f" {escalation_note}" if escalation_note else ""),
                     meta={"action_id": str(action.id), "success": success, "deterministic_reason": deterministic_reason,
                           "reinvestigation_count": incident.reinvestigation_count}))
    db.commit(); db.refresh(action)
    return action