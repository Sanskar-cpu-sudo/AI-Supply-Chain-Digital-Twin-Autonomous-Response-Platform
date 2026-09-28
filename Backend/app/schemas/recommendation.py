import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.enums import ActionStatus, VerificationResult


class RecommendationDecisionRequest(BaseModel):
    reason: str | None = None


class ActionOut(BaseModel):
    id: uuid.UUID
    action_type: str
    status: ActionStatus
    executed_at: datetime | None
    result: dict | None
    verification_result: VerificationResult
    verification_before: dict | None
    verification_after: dict | None
    verification_reason: str | None
    created_at: datetime

    model_config = {"from_attributes": True}