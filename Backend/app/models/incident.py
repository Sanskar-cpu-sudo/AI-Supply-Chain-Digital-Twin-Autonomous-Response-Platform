import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDPKMixin, company_fk
from app.models.enums import IncidentSeverity, IncidentStatus, IncidentType


class Incident(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "incidents"

    company_id: Mapped[uuid.UUID] = company_fk()

    type: Mapped[IncidentType] = mapped_column(Enum(IncidentType, name="incident_type"), nullable=False)
    severity: Mapped[IncidentSeverity] = mapped_column(
        Enum(IncidentSeverity, name="incident_severity"), nullable=False
    )
    status: Mapped[IncidentStatus] = mapped_column(
        Enum(IncidentStatus, name="incident_status"), nullable=False, default=IncidentStatus.OPEN
    )
    description: Mapped[str | None] = mapped_column(Text)

    # Nullable FKs -- not every incident type maps to every entity
    # (a demand spike may have no shipment_id, a supplier delay may
    # have no specific warehouse, etc).
    shipment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("shipments.id"))
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("suppliers.id"))
    product_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"))
    warehouse_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("warehouses.id"))

    # Re-investigation loop guardrail (Phase 21): capped at 2 in app logic.
    reinvestigation_count: Mapped[int] = mapped_column(default=0, nullable=False)

    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    shipment: Mapped["Shipment | None"] = relationship(back_populates="incidents")
    investigations: Mapped[list["Investigation"]] = relationship(
        back_populates="incident", cascade="all, delete-orphan", order_by="Investigation.created_at"
    )
    recommendations: Mapped[list["Recommendation"]] = relationship(
        back_populates="incident", cascade="all, delete-orphan"
    )
    actions: Mapped[list["Action"]] = relationship(back_populates="incident", cascade="all, delete-orphan")
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="incident", cascade="all, delete-orphan")