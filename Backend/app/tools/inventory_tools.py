import uuid

from sqlalchemy.orm import Session

from app.models.operations import Inventory


def get_inventory(db: Session, company_id, product_id: str | None = None, warehouse_id: str | None = None) -> dict:
    """
    Fetch current inventory levels, optionally filtered by product and/or
    warehouse. Returns a list of rows since a product can exist at
    multiple warehouses.
    """
    q = db.query(Inventory).filter(Inventory.company_id == company_id)

    if product_id:
        try:
            q = q.filter(Inventory.product_id == uuid.UUID(str(product_id)))
        except ValueError:
            return {"error": f"'{product_id}' is not a valid product id"}

    if warehouse_id:
        try:
            q = q.filter(Inventory.warehouse_id == uuid.UUID(str(warehouse_id)))
        except ValueError:
            return {"error": f"'{warehouse_id}' is not a valid warehouse id"}

    rows = q.all()
    if not rows:
        return {"error": "No inventory rows found matching those filters"}

    return {
        "inventory": [
            {
                "id": str(r.id),
                "product_id": str(r.product_id),
                "warehouse_id": str(r.warehouse_id),
                "quantity_on_hand": r.quantity_on_hand,
                "reorder_point": r.reorder_point,
                "safety_stock": r.safety_stock,
                "below_reorder_point": r.quantity_on_hand < r.reorder_point,
            }
            for r in rows
        ]
    }