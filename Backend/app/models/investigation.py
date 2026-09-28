import uuid

from sqlalchemy import Enum, Float, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDPKMixin, company_fk
from app.models.enums import InvestigationStatus


class Investigation(UUIDPKMixin, TimestampMixin, Base):
    """
    One row per Investigation Agent run against an incident. An incident
    can have multiple investigations if the re-investigation loop
    (Phase 21) kicks in after a failed verification.
    """

    __tablename__ = "investigations"

    company_id: Mapped[uuid.UUID] = company_fk()
    incident_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("incidents.id"), nullable=False)

    status: Mapped[InvestigationStatus] = mapped_column(
        Enum(InvestigationStatus, name="investigation_status"), nullable=False
    )
    root_cause: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[list | None] = mapped_column(JSONB)          # list[str]
    impact: Mapped[dict | None] = mapped_column(JSONB)            # {"orders_at_risk": 1200, "stockout_days": 2}
    confidence: Mapped[float | None] = mapped_column(Float)

    # Full trace of tool calls the agent made, for the audit timeline
    # and for the tool-selection-accuracy metric in the eval harness (Phase 24).
    tool_calls: Mapped[list | None] = mapped_column(JSONB)

    incident: Mapped["Incident"] = relationship(back_populates="investigations")
    recommendations: Mapped[list["Recommendation"]] = relationship(back_populates="investigation")