import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models.action import Action
from app.models.company import User
from app.schemas.recommendation import ActionOut
from app.services.deps import get_current_user
from app.services.verification_service import VerificationError, verify_action

router = APIRouter(prefix="/actions", tags=["actions"])


def _get_action_or_404(db: Session, action_id: uuid.UUID, company_id) -> Action:
    action = db.query(Action).filter(Action.id == action_id, Action.company_id == company_id).first()
    if action is None:
        raise HTTPException(status_code=404, detail="Action not found")
    return action


@router.get("/{action_id}", response_model=ActionOut)
def get_action(
    action_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _get_action_or_404(db, action_id, current_user.company_id)


@router.post("/{action_id}/verify", response_model=ActionOut)
def verify_action_route(
    action_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Compares before/after state and determines success/failure
    deterministically (Phase 20 -- no LLM in the actual verdict, only in
    the explanation). On success, the incident is marked RESOLVED. On
    failure, the incident is left as-is for Phase 21's re-investigation
    loop to handle.
    """
    action = _get_action_or_404(db, action_id, current_user.company_id)

    try:
        verified_action = verify_action(db, current_user.company_id, action)
    except VerificationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return verified_action