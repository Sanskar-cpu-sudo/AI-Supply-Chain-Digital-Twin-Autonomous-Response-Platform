import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDPKMixin, company_fk
from app.models.enums import RecommendationStatus


class Recommendation(UUIDPKMixin, TimestampMixin, Base):
    """
    Decision Agent's chosen option + OR-Tools' numbers behind it.
    Sits behind the human approval gate (Phase 18) -- nothing here
    triggers an Action until approved_by/approved_at are set.
    """

    __tablename__ = "recommendations"

    company_id: Mapped[uuid.UUID] = company_fk()
    incident_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("incidents.id"), nullable=False)
    investigation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("investigations.id"), nullable=False
    )

    option_chosen: Mapped[str] = mapped_column(String(255), nullable=False)   # e.g. "use_supplier_b"
    # Every option the Decision Agent considered + OR-Tools' scoring for each,
    # e.g. [{"option": "wait", "cost": 0, "delay_days": 4, "stockout": true}, ...]
    options_considered: Mapped[list] = mapped_column(JSONB, nullable=False)

    estimated_cost: Mapped[float | None] = mapped_column(Float)
    expected_delay_days: Mapped[int | None] = mapped_column(Integer)
    stockout_risk: Mapped[str | None] = mapped_column(String(50))    # "low" | "medium" | "high"

    reasoning: Mapped[str | None] = mapped_column(Text)   # LLM's plain-English explanation of the OR-Tools result
    confidence: Mapped[float | None] = mapped_column(Float)

    status: Mapped[RecommendationStatus] = mapped_column(
        Enum(RecommendationStatus, name="recommendation_status"),
        nullable=False,
        default=RecommendationStatus.PENDING,
    )
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    decision_reason: Mapped[str | None] = mapped_column(Text)   # e.g. "Rejected - Supplier B pricing too high"
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    incident: Mapped["Incident"] = relationship(back_populates="recommendations")
    investigation: Mapped["Investigation"] = relationship(back_populates="recommendations")
    action: Mapped["Action | None"] = relationship(back_populates="recommendation", uselist=False)