import uuid

from sqlalchemy.orm import Session

from app.models.operations import Order


def get_orders(db: Session, company_id, product_id: str | None = None, limit: int = 20) -> dict:
    """
    Fetch recent orders, optionally filtered by product. Used by the
    Investigation Agent to assess how many customer orders are at risk
    from a shipment delay or inventory shortage.
    """
    q = db.query(Order).filter(Order.company_id == company_id)

    if product_id:
        try:
            q = q.filter(Order.product_id == uuid.UUID(str(product_id)))
        except ValueError:
            return {"error": f"'{product_id}' is not a valid product id"}

    orders = q.order_by(Order.created_at.desc()).limit(limit).all()
    if not orders:
        return {"error": "No orders found matching those filters"}

    return {
        "orders": [
            {
                "id": str(o.id),
                "customer_name": o.customer_name,
                "product_id": str(o.product_id),
                "quantity": o.quantity,
                "status": o.status.value,
                "requested_date": o.requested_date.isoformat(),
                "promised_date": o.promised_date.isoformat() if o.promised_date else None,
            }
            for o in orders
        ],
        "total_quantity_at_risk": sum(o.quantity for o in orders if o.status.value in ("pending", "at_risk")),
    }