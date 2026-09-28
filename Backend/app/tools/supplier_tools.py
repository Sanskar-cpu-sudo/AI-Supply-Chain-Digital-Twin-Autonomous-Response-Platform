import uuid

from sqlalchemy.orm import Session

from app.models.master_data import Supplier


def get_supplier(db: Session, company_id, supplier_id: str) -> dict:
    """Fetch full details of a single supplier by id, including reliability score."""
    try:
        supplier_uuid = uuid.UUID(str(supplier_id))
    except ValueError:
        return {"error": f"'{supplier_id}' is not a valid supplier id"}

    supplier = (
        db.query(Supplier)
        .filter(Supplier.id == supplier_uuid, Supplier.company_id == company_id)
        .first()
    )
    if supplier is None:
        return {"error": f"No supplier found with id {supplier_id}"}

    return {
        "id": str(supplier.id),
        "name": supplier.name,
        "contact_email": supplier.contact_email,
        "reliability_score": supplier.reliability_score,
        "is_approved": supplier.is_approved,
    }