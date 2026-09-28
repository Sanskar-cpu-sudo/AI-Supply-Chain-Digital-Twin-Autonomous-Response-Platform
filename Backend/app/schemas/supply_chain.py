import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.enums import OrderStatus, ShipmentStatus


# ---------- Supplier ----------
class SupplierCreate(BaseModel):
    name: str
    contact_email: str | None = None
    contact_phone: str | None = None
    reliability_score: float = Field(default=1.0, ge=0, le=1)
    is_approved: bool = True


class SupplierOut(BaseModel):
    id: uuid.UUID
    name: str
    contact_email: str | None
    contact_phone: str | None
    reliability_score: float
    is_approved: bool

    model_config = {"from_attributes": True}


# ---------- Product ----------
class ProductCreate(BaseModel):
    sku: str
    name: str
    description: str | None = None
    unit_cost: float = 0.0


class ProductOut(BaseModel):
    id: uuid.UUID
    sku: str
    name: str
    description: str | None
    unit_cost: float

    model_config = {"from_attributes": True}


# ---------- Warehouse ----------
class WarehouseCreate(BaseModel):
    name: str
    location: str | None = None
    capacity: int | None = None


class WarehouseOut(BaseModel):
    id: uuid.UUID
    name: str
    location: str | None
    capacity: int | None

    model_config = {"from_attributes": True}


# ---------- Inventory ----------
class InventoryCreate(BaseModel):
    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    quantity_on_hand: int = 0
    reorder_point: int = 0
    safety_stock: int = 0


class InventoryOut(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    quantity_on_hand: int
    reorder_point: int
    safety_stock: int

    model_config = {"from_attributes": True}


# ---------- Order ----------
class OrderCreate(BaseModel):
    customer_name: str
    product_id: uuid.UUID
    quantity: int
    requested_date: date
    promised_date: date | None = None


class OrderOut(BaseModel):
    id: uuid.UUID
    customer_name: str
    product_id: uuid.UUID
    quantity: int
    status: OrderStatus
    requested_date: date
    promised_date: date | None

    model_config = {"from_attributes": True}


# ---------- Shipment ----------
class ShipmentCreate(BaseModel):
    supplier_id: uuid.UUID
    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    order_id: uuid.UUID | None = None
    quantity: int
    expected_delivery: datetime


class ShipmentOut(BaseModel):
    id: uuid.UUID
    supplier_id: uuid.UUID
    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    order_id: uuid.UUID | None
    quantity: int
    status: ShipmentStatus
    expected_delivery: datetime
    actual_delivery: datetime | None
    delay_days: int

    model_config = {"from_attributes": True}