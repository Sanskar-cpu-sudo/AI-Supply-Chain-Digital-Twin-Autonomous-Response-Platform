import uuid

from sqlalchemy import Boolean, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDPKMixin, company_fk


class Supplier(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "suppliers"

    company_id: Mapped[uuid.UUID] = company_fk()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_email: Mapped[str | None] = mapped_column(String(255))
    contact_phone: Mapped[str | None] = mapped_column(String(50))
    # 0-1, updated over time from on-time delivery history; used by the
    # Decision Agent / OR-Tools when weighing "use backup supplier" options.
    reliability_score: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    company: Mapped["Company"] = relationship(back_populates="suppliers")
    shipments: Mapped[list["Shipment"]] = relationship(back_populates="supplier")


class Product(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "products"

    company_id: Mapped[uuid.UUID] = company_fk()
    sku: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    unit_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    company: Mapped["Company"] = relationship(back_populates="products")


class Warehouse(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "warehouses"

    company_id: Mapped[uuid.UUID] = company_fk()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    location: Mapped[str | None] = mapped_column(String(255))
    capacity: Mapped[int | None] = mapped_column(Integer)

    company: Mapped["Company"] = relationship(back_populates="warehouses")