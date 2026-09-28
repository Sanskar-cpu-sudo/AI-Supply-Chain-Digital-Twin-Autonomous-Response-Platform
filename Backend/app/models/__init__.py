"""
Import every model here so `Base.metadata` is fully populated in one place.
Alembic's env.py imports this module (via app.database.base import Base)
to know what tables should exist when autogenerating migrations.
"""
from app.models.action import Action
from app.models.audit_log import AuditLog
from app.models.company import Company, User
from app.models.document import Document, DocumentChunk
from app.models.incident import Incident
from app.models.investigation import Investigation
from app.models.master_data import Product, Supplier, Warehouse
from app.models.operations import Inventory, Order, Shipment
from app.models.recommendation import Recommendation

__all__ = [
    "Company",
    "User",
    "Supplier",
    "Product",
    "Warehouse",
    "Inventory",
    "Order",
    "Shipment",
    "Incident",
    "Investigation",
    "Recommendation",
    "Action",
    "AuditLog",
    "Document",
    "DocumentChunk",
]