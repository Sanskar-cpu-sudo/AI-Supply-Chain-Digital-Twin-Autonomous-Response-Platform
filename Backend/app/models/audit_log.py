import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database.base import Base, UUIDPKMixin, company_fk
from app.models.enums import ActorType


class AuditLog(UUIDPKMixin, Base):
    """
    Append-only event log for the incident timeline (Phase 23):
    "09:31 Incident detected", "09:32 getSupplier()", etc.
    Also where we stash LLM latency/cost/tool-call metadata for
    the eval harness (Phase 24) to aggregate later.

    No updated_at on purpose -- these rows are never mutated.
    """

    __tablename__ = "audit_logs"

    company_id: Mapped[uuid.UUID] = company_fk()
    incident_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("incidents.id"))

    actor_type: Mapped[ActorType] = mapped_column(Enum(ActorType, name="actor_type"), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))   # user_id if actor_type == USER

    event_type: Mapped[str] = mapped_column(String(100), nullable=False)   # "incident_detected", "tool_call", ...
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    # Freeform bag for latency_ms, llm_cost_usd, tool_name, error, etc.
    meta: Mapped[dict | None] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    incident: Mapped["Incident | None"] = relationship(back_populates="audit_logs")