import uuid

from sqlalchemy.orm import Session

from app.models.master_data import Warehouse


def get_warehouse(db: Session, company_id, warehouse_id: str) -> dict:
    """Fetch details of a single warehouse by id."""
    try:
        warehouse_uuid = uuid.UUID(str(warehouse_id))
    except ValueError:
        return {"error": f"'{warehouse_id}' is not a valid warehouse id"}

    warehouse = (
        db.query(Warehouse)
        .filter(Warehouse.id == warehouse_uuid, Warehouse.company_id == company_id)
        .first()
    )
    if warehouse is None:
        return {"error": f"No warehouse found with id {warehouse_id}"}

    return {
        "id": str(warehouse.id),
        "name": warehouse.name,
        "location": warehouse.location,
        "capacity": warehouse.capacity,
    }