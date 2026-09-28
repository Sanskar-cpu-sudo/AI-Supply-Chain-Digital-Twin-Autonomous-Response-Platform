import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDPKMixin, company_fk
from app.models.enums import OrderStatus, ShipmentStatus


class Inventory(UUIDPKMixin, TimestampMixin, Base):
    """
    Current stock level of a product at a warehouse.
    One row per (product, warehouse) -- the Monitoring system (Phase 9)
    watches quantity_on_hand vs reorder_point on this table.
    """

    __tablename__ = "inventory"
    __table_args__ = (UniqueConstraint("product_id", "warehouse_id", name="uq_inventory_product_warehouse"),)

    company_id: Mapped[uuid.UUID] = company_fk()
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False)

    quantity_on_hand: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reorder_point: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    safety_stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    product: Mapped["Product"] = relationship()
    warehouse: Mapped["Warehouse"] = relationship()


class Order(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "orders"

    company_id: Mapped[uuid.UUID] = company_fk()
    customer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, name="order_status"), nullable=False, default=OrderStatus.PENDING
    )
    requested_date: Mapped[date] = mapped_column(Date, nullable=False)
    promised_date: Mapped[date | None] = mapped_column(Date)

    product: Mapped["Product"] = relationship()
    shipments: Mapped[list["Shipment"]] = relationship(back_populates="order")


class Shipment(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "shipments"

    company_id: Mapped[uuid.UUID] = company_fk()
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False)
    order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=True)

    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ShipmentStatus] = mapped_column(
        Enum(ShipmentStatus, name="shipment_status"), nullable=False, default=ShipmentStatus.SCHEDULED
    )
    expected_delivery: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actual_delivery: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delay_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    supplier: Mapped["Supplier"] = relationship(back_populates="shipments")
    product: Mapped["Product"] = relationship()
    warehouse: Mapped["Warehouse"] = relationship()
    order: Mapped["Order | None"] = relationship(back_populates="shipments")
    incidents: Mapped[list["Incident"]] = relationship(back_populates="shipment")