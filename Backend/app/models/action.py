import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDPKMixin, company_fk
from app.models.enums import ActionStatus, VerificationResult


class Action(UUIDPKMixin, TimestampMixin, Base):
    """
    Deterministic execution of an approved recommendation (Phase 19),
    plus the Verification Agent's before/after check (Phase 20).
    Only ever created after a Recommendation.status == APPROVED.
    """

    __tablename__ = "actions"

    company_id: Mapped[uuid.UUID] = company_fk()
    incident_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("incidents.id"), nullable=False)
    recommendation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recommendations.id"), nullable=False, unique=True
    )

    action_type: Mapped[str] = mapped_column(String(100), nullable=False)   # e.g. "create_purchase_order"
    status: Mapped[ActionStatus] = mapped_column(
        Enum(ActionStatus, name="action_status"), nullable=False, default=ActionStatus.PENDING
    )
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict | None] = mapped_column(JSONB)   # deterministic-code output, e.g. new PO id, updated qty

    # Verification Agent fields (Phase 20)
    verification_result: Mapped[VerificationResult] = mapped_column(
        Enum(VerificationResult, name="verification_result"), nullable=False, default=VerificationResult.PENDING
    )
    verification_before: Mapped[dict | None] = mapped_column(JSONB)   # snapshot of key metrics pre-action
    verification_after: Mapped[dict | None] = mapped_column(JSONB)    # snapshot post-action
    verification_reason: Mapped[str | None] = mapped_column(String(500))

    incident: Mapped["Incident"] = relationship(back_populates="actions")
    recommendation: Mapped["Recommendation"] = relationship(back_populates="action")