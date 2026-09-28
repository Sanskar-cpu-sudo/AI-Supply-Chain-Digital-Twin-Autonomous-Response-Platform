import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models.audit_log import AuditLog
from app.models.company import User
from app.models.enums import ActorType, IncidentStatus, RecommendationStatus
from app.models.incident import Incident
from app.models.recommendation import Recommendation
from app.schemas.incident import RecommendationOut
from app.schemas.recommendation import ActionOut, RecommendationDecisionRequest
from app.services.action_service import ActionError, execute_action
from app.services.deps import get_current_user

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


def _get_recommendation_or_404(db: Session, recommendation_id: uuid.UUID, company_id) -> Recommendation:
    recommendation = (
        db.query(Recommendation)
        .filter(Recommendation.id == recommendation_id, Recommendation.company_id == company_id)
        .first()
    )
    if recommendation is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    return recommendation


@router.get("/{recommendation_id}", response_model=RecommendationOut)
def get_recommendation(
    recommendation_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _get_recommendation_or_404(db, recommendation_id, current_user.company_id)


@router.post("/{recommendation_id}/approve", response_model=RecommendationOut)
def approve_recommendation(
    recommendation_id: uuid.UUID,
    payload: RecommendationDecisionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    The human approval gate. Nothing downstream (Phase 19's Action
    Service) is allowed to execute anything until a recommendation is
    APPROVED here by an actual person -- this endpoint is the only thing
    that can flip that switch.
    """
    recommendation = _get_recommendation_or_404(db, recommendation_id, current_user.company_id)

    if recommendation.status != RecommendationStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail=f"Recommendation is already '{recommendation.status.value}' -- can only decide on a PENDING recommendation.",
        )

    recommendation.status = RecommendationStatus.APPROVED
    recommendation.decided_by_user_id = current_user.id
    recommendation.decision_reason = payload.reason
    recommendation.decided_at = datetime.now(timezone.utc)

    incident = db.query(Incident).filter(Incident.id == recommendation.incident_id).first()
    incident.status = IncidentStatus.APPROVED

    db.add(
        AuditLog(
            company_id=current_user.company_id,
            incident_id=incident.id,
            actor_type=ActorType.USER,
            actor_id=current_user.id,
            event_type="recommendation_approved",
            message=f"Recommendation ({recommendation.option_chosen}) approved by {current_user.full_name}."
            + (f" Reason: {payload.reason}" if payload.reason else ""),
        )
    )
    db.commit()
    db.refresh(recommendation)
    return recommendation


@router.post("/{recommendation_id}/reject", response_model=RecommendationOut)
def reject_recommendation(
    recommendation_id: uuid.UUID,
    payload: RecommendationDecisionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Rejecting sends the incident back to INVESTIGATING (not a dead end):
    the underlying investigation is still valid, so a manager can trigger
    POST /incidents/{id}/recommend again -- e.g. after adjusting company
    policy documents, or simply wanting the Decision Agent to try again --
    without redoing the investigation from scratch.
    """
    recommendation = _get_recommendation_or_404(db, recommendation_id, current_user.company_id)

    if recommendation.status != RecommendationStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail=f"Recommendation is already '{recommendation.status.value}' -- can only decide on a PENDING recommendation.",
        )

    recommendation.status = RecommendationStatus.REJECTED
    recommendation.decided_by_user_id = current_user.id
    recommendation.decision_reason = payload.reason
    recommendation.decided_at = datetime.now(timezone.utc)

    incident = db.query(Incident).filter(Incident.id == recommendation.incident_id).first()
    incident.status = IncidentStatus.INVESTIGATING

    db.add(
        AuditLog(
            company_id=current_user.company_id,
            incident_id=incident.id,
            actor_type=ActorType.USER,
            actor_id=current_user.id,
            event_type="recommendation_rejected",
            message=f"Recommendation ({recommendation.option_chosen}) rejected by {current_user.full_name}."
            + (f" Reason: {payload.reason}" if payload.reason else " (no reason given)"),
        )
    )
    db.commit()
    db.refresh(recommendation)
    return recommendation


@router.post("/{recommendation_id}/execute", response_model=ActionOut)
def execute_recommendation(
    recommendation_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Executes an APPROVED recommendation via deterministic code (Phase 19
    -- no LLM involved). Kept as a separate explicit trigger rather than
    firing automatically inside /approve, so execution can later be
    moved to a background worker or require a second confirmation
    without changing the approval endpoint's behavior.
    """
    recommendation = _get_recommendation_or_404(db, recommendation_id, current_user.company_id)

    try:
        action = execute_action(db, current_user.company_id, recommendation)
    except ActionError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return action