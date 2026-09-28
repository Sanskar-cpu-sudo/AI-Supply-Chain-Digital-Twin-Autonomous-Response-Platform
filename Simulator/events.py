import random
import uuid
from datetime import datetime, timedelta, timezone

from app.models.enums import OrderStatus, ShipmentStatus
from app.models.master_data import Product, Supplier, Warehouse
from app.models.operations import Inventory, Order, Shipment


def _pick_active_shipment(db, company_id, supplier_id=None, warehouse_id=None):
    q = db.query(Shipment).filter(Shipment.company_id == company_id, Shipment.status.in_([ShipmentStatus.SCHEDULED, ShipmentStatus.IN_TRANSIT]))
    if supplier_id: q = q.filter(Shipment.supplier_id == supplier_id)
    if warehouse_id: q = q.filter(Shipment.warehouse_id == warehouse_id)
    candidates = q.all()
    return random.choice(candidates) if candidates else None


def trigger_shipment_delay(db, company_id, shipment_id=None, delay_days=None):
    shipment = db.get(Shipment, shipment_id) if shipment_id else _pick_active_shipment(db, company_id)
    if shipment is None:
        return {"event": "SHIPMENT_DELAY", "error": "no active shipment available to delay"}
    delay_days = delay_days or random.randint(2, 6)
    shipment.delay_days += delay_days
    shipment.expected_delivery += timedelta(days=delay_days)
    shipment.status = ShipmentStatus.DELAYED
    db.commit()
    return {"event": "SHIPMENT_DELAY", "shipment_id": str(shipment.id), "delay_days": delay_days,
            "new_expected_delivery": shipment.expected_delivery.isoformat()}


def trigger_supplier_delay(db, company_id, supplier_id=None, delay_days=None):
    if supplier_id:
        supplier = db.get(Supplier, supplier_id)
    else:
        candidates = db.query(Supplier).filter(Supplier.company_id == company_id).all()
        supplier = random.choice(candidates) if candidates else None
    if supplier is None:
        return {"event": "SUPPLIER_DELAY", "error": "no supplier available"}
    delay_days = delay_days or random.randint(2, 5)
    affected = db.query(Shipment).filter(Shipment.company_id == company_id, Shipment.supplier_id == supplier.id,
                                          Shipment.status.in_([ShipmentStatus.SCHEDULED, ShipmentStatus.IN_TRANSIT])).all()
    for shipment in affected:
        shipment.delay_days += delay_days
        shipment.expected_delivery += timedelta(days=delay_days)
        shipment.status = ShipmentStatus.DELAYED
    supplier.reliability_score = round(max(0.0, supplier.reliability_score - random.uniform(0.05, 0.15)), 2)
    db.commit()
    return {"event": "SUPPLIER_DELAY", "supplier_id": str(supplier.id), "supplier_name": supplier.name,
            "delay_days": delay_days, "shipments_affected": [str(s.id) for s in affected],
            "new_reliability_score": supplier.reliability_score}


def trigger_demand_spike(db, company_id, product_id=None, pct_increase=None):
    from app.models.operations import Order as _Order
    product = db.get(Product, product_id) if product_id else random.choice(db.query(Product).filter(Product.company_id == company_id).all())
    if product is None:
        return {"event": "DEMAND_SPIKE", "error": "no product available"}
    existing_orders = db.query(_Order).filter(_Order.company_id == company_id, _Order.product_id == product.id).all()
    baseline_qty = sum(o.quantity for o in existing_orders) / len(existing_orders) if existing_orders else 300
    pct_increase = pct_increase or random.uniform(3.0, 5.0)  # large margin -- the comparison average includes
    # this new order itself, diluting the ratio (Phase 13 finding)
    spike_qty = int(baseline_qty * (1 + pct_increase))
    order = Order(company_id=company_id, customer_name="Surge Demand Customer", product_id=product.id,
                  quantity=spike_qty, status=OrderStatus.PENDING, requested_date=datetime.now(timezone.utc).date(),
                  promised_date=(datetime.now(timezone.utc) + timedelta(days=5)).date())
    db.add(order); db.commit(); db.refresh(order)
    return {"event": "DEMAND_SPIKE", "product_id": str(product.id), "product_name": product.name,
            "pct_increase": round(pct_increase, 2), "order_id": str(order.id), "order_quantity": spike_qty}


def trigger_inventory_shortage(db, company_id, product_id=None, warehouse_id=None):
    q = db.query(Inventory).filter(Inventory.company_id == company_id)
    if product_id: q = q.filter(Inventory.product_id == product_id)
    if warehouse_id: q = q.filter(Inventory.warehouse_id == warehouse_id)
    candidates = q.all()
    if not candidates:
        return {"event": "INVENTORY_SHORTAGE", "error": "no inventory row available"}
    inventory = random.choice(candidates)
    old_qty = inventory.quantity_on_hand
    inventory.quantity_on_hand = max(0, inventory.reorder_point - random.randint(10, 50))
    db.commit()
    return {"event": "INVENTORY_SHORTAGE", "inventory_id": str(inventory.id), "product_id": str(inventory.product_id),
            "warehouse_id": str(inventory.warehouse_id), "quantity_before": old_qty,
            "quantity_after": inventory.quantity_on_hand, "reorder_point": inventory.reorder_point}


def trigger_logistics_disruption(db, company_id, delay_days=None, affected_fraction=0.5):
    delay_days = delay_days or random.randint(3, 8)
    active = db.query(Shipment).filter(Shipment.company_id == company_id, Shipment.status.in_([ShipmentStatus.SCHEDULED, ShipmentStatus.IN_TRANSIT])).all()
    if not active:
        return {"event": "LOGISTICS_DISRUPTION", "error": "no active shipments to disrupt"}
    sample_size = max(1, int(len(active) * affected_fraction))
    affected = random.sample(active, sample_size)
    for shipment in affected:
        shipment.delay_days += delay_days
        shipment.expected_delivery += timedelta(days=delay_days)
        shipment.status = ShipmentStatus.DELAYED
    db.commit()
    return {"event": "LOGISTICS_DISRUPTION", "delay_days": delay_days, "shipments_affected": [str(s.id) for s in affected],
            "shipments_affected_count": len(affected)}


def trigger_warehouse_unavailable(db, company_id, warehouse_id=None, delay_days=None):
    warehouse = db.get(Warehouse, warehouse_id) if warehouse_id else random.choice(db.query(Warehouse).filter(Warehouse.company_id == company_id).all())
    if warehouse is None:
        return {"event": "WAREHOUSE_UNAVAILABLE", "error": "no warehouse available"}
    delay_days = delay_days or random.randint(2, 5)
    affected = db.query(Shipment).filter(Shipment.company_id == company_id, Shipment.warehouse_id == warehouse.id,
                                          Shipment.status.in_([ShipmentStatus.SCHEDULED, ShipmentStatus.IN_TRANSIT])).all()
    for shipment in affected:
        shipment.delay_days += delay_days
        shipment.expected_delivery += timedelta(days=delay_days)
        shipment.status = ShipmentStatus.DELAYED
    db.commit()
    return {"event": "WAREHOUSE_UNAVAILABLE", "warehouse_id": str(warehouse.id), "warehouse_name": warehouse.name,
            "delay_days": delay_days, "shipments_affected": [str(s.id) for s in affected]}


EVENT_REGISTRY = {
    "SHIPMENT_DELAY": trigger_shipment_delay, "SUPPLIER_DELAY": trigger_supplier_delay,
    "DEMAND_SPIKE": trigger_demand_spike, "INVENTORY_SHORTAGE": trigger_inventory_shortage,
    "LOGISTICS_DISRUPTION": trigger_logistics_disruption, "WAREHOUSE_UNAVAILABLE": trigger_warehouse_unavailable,
}
# """
# Each function here injects one real, detectable problem into the
# database -- not a fake notification, an actual state change. Phase 9's
# Monitoring system will later find these with plain SQL rules like
# `if actual_delivery > expected_delivery` or `if quantity_on_hand < reorder_point`.

# Every function returns a small dict describing what happened, in the
# same shape as the plan's example:
#     {"event": "SHIPMENT_DELAY", "shipment_id": 101, "delay_days": 4}
# This return value is what a caller (CLI, test scenario, or later the
# eval harness) logs or asserts against.
# """
# import random
# import uuid
# from datetime import datetime, timedelta, timezone

# from app.models.enums import OrderStatus, ShipmentStatus
# from app.models.master_data import Product, Supplier, Warehouse
# from app.models.operations import Inventory, Order, Shipment


# def _pick_active_shipment(db, company_id, supplier_id=None, warehouse_id=None) -> Shipment | None:
#     q = db.query(Shipment).filter(
#         Shipment.company_id == company_id,
#         Shipment.status.in_([ShipmentStatus.SCHEDULED, ShipmentStatus.IN_TRANSIT]),
#     )
#     if supplier_id:
#         q = q.filter(Shipment.supplier_id == supplier_id)
#     if warehouse_id:
#         q = q.filter(Shipment.warehouse_id == warehouse_id)
#     candidates = q.all()
#     return random.choice(candidates) if candidates else None


# def trigger_shipment_delay(db, company_id, shipment_id: uuid.UUID | None = None, delay_days: int | None = None) -> dict:
#     """A single shipment gets delayed -- the simplest, most common incident."""
#     shipment = (
#         db.get(Shipment, shipment_id)
#         if shipment_id
#         else _pick_active_shipment(db, company_id)
#     )
#     if shipment is None:
#         return {"event": "SHIPMENT_DELAY", "error": "no active shipment available to delay"}

#     delay_days = delay_days or random.randint(2, 6)
#     shipment.delay_days += delay_days
#     shipment.expected_delivery += timedelta(days=delay_days)
#     shipment.status = ShipmentStatus.DELAYED
#     db.commit()

#     return {
#         "event": "SHIPMENT_DELAY",
#         "shipment_id": str(shipment.id),
#         "delay_days": delay_days,
#         "new_expected_delivery": shipment.expected_delivery.isoformat(),
#     }


# def trigger_supplier_delay(db, company_id, supplier_id: uuid.UUID | None = None, delay_days: int | None = None) -> dict:
#     """
#     A supplier-side problem (production delay, factory issue) -- delays
#     EVERY open shipment from that supplier, and dents their reliability
#     score so the Decision Agent's "use backup supplier" option later
#     has real signal to reason with.
#     """
#     if supplier_id:
#         supplier = db.get(Supplier, supplier_id)
#     else:
#         candidates = db.query(Supplier).filter(Supplier.company_id == company_id).all()
#         supplier = random.choice(candidates) if candidates else None
#     if supplier is None:
#         return {"event": "SUPPLIER_DELAY", "error": "no supplier available"}

#     delay_days = delay_days or random.randint(2, 5)
#     affected = (
#         db.query(Shipment)
#         .filter(
#             Shipment.company_id == company_id,
#             Shipment.supplier_id == supplier.id,
#             Shipment.status.in_([ShipmentStatus.SCHEDULED, ShipmentStatus.IN_TRANSIT]),
#         )
#         .all()
#     )
#     for shipment in affected:
#         shipment.delay_days += delay_days
#         shipment.expected_delivery += timedelta(days=delay_days)
#         shipment.status = ShipmentStatus.DELAYED

#     supplier.reliability_score = round(max(0.0, supplier.reliability_score - random.uniform(0.05, 0.15)), 2)
#     db.commit()

#     return {
#         "event": "SUPPLIER_DELAY",
#         "supplier_id": str(supplier.id),
#         "supplier_name": supplier.name,
#         "delay_days": delay_days,
#         "shipments_affected": [str(s.id) for s in affected],
#         "new_reliability_score": supplier.reliability_score,
#     }


# def trigger_demand_spike(db, company_id, product_id: uuid.UUID | None = None, pct_increase: float | None = None) -> dict:
#     """
#     Simulates a sudden surge in customer demand: creates a new, unusually
#     large order for a product. Monitoring will later flag this against
#     current inventory levels to see if it puts orders at risk.

#     IMPORTANT: the spike is sized relative to THIS PRODUCT'S ACTUAL
#     historical average order quantity, not a fixed guess. An earlier
#     version used a hardcoded 300-unit baseline, which silently failed to
#     trigger check_demand_spikes' detection whenever a product's real
#     historical average (itself randomly generated) happened to exceed
#     300 -- the "spike" wasn't actually a spike relative to that
#     product's own data. Caught via Phase 13 scenario testing.
#     """
#     from app.models.operations import Order as _Order  # local import to avoid circular import at module load

#     product = db.get(Product, product_id) if product_id else (
#         random.choice(db.query(Product).filter(Product.company_id == company_id).all())
#     )
#     if product is None:
#         return {"event": "DEMAND_SPIKE", "error": "no product available"}

#     existing_orders = db.query(_Order).filter(_Order.company_id == company_id, _Order.product_id == product.id).all()
#     baseline_qty = (
#         sum(o.quantity for o in existing_orders) / len(existing_orders) if existing_orders else 300
#     )

#     pct_increase = pct_increase or random.uniform(3.0, 5.0)  # deliberately large margin: check_demand_spikes'
#     # average is computed AFTER this order is added, which dilutes the ratio (more so for
#     # products with few historical orders) -- a small margin like 1.8x can still miss the
#     # threshold once the new order is folded into its own comparison average.
#     spike_qty = int(baseline_qty * (1 + pct_increase))

#     order = Order(
#         company_id=company_id,
#         customer_name="Surge Demand Customer",
#         product_id=product.id,
#         quantity=spike_qty,
#         status=OrderStatus.PENDING,
#         requested_date=datetime.now(timezone.utc).date(),
#         promised_date=(datetime.now(timezone.utc) + timedelta(days=5)).date(),
#     )
#     db.add(order)
#     db.commit()
#     db.refresh(order)

#     return {
#         "event": "DEMAND_SPIKE",
#         "product_id": str(product.id),
#         "product_name": product.name,
#         "pct_increase": round(pct_increase, 2),
#         "order_id": str(order.id),
#         "order_quantity": spike_qty,
#     }


# def trigger_inventory_shortage(db, company_id, product_id: uuid.UUID | None = None, warehouse_id: uuid.UUID | None = None) -> dict:
#     """Directly drops stock below the reorder point -- the cleanest way
#     to test the inventory_shortage incident path without waiting for
#     orders to naturally deplete stock."""
#     q = db.query(Inventory).filter(Inventory.company_id == company_id)
#     if product_id:
#         q = q.filter(Inventory.product_id == product_id)
#     if warehouse_id:
#         q = q.filter(Inventory.warehouse_id == warehouse_id)
#     candidates = q.all()
#     if not candidates:
#         return {"event": "INVENTORY_SHORTAGE", "error": "no inventory row available"}

#     inventory = random.choice(candidates)
#     old_qty = inventory.quantity_on_hand
#     inventory.quantity_on_hand = max(0, inventory.reorder_point - random.randint(10, 50))
#     db.commit()

#     return {
#         "event": "INVENTORY_SHORTAGE",
#         "inventory_id": str(inventory.id),
#         "product_id": str(inventory.product_id),
#         "warehouse_id": str(inventory.warehouse_id),
#         "quantity_before": old_qty,
#         "quantity_after": inventory.quantity_on_hand,
#         "reorder_point": inventory.reorder_point,
#     }


# def trigger_logistics_disruption(db, company_id, delay_days: int | None = None, affected_fraction: float = 0.5) -> dict:
#     """
#     A port closure or broad logistics disruption -- unlike a single
#     shipment delay, this hits a chunk of ALL active shipments at once,
#     regardless of supplier. Meant to stress-test the system with a
#     higher-severity, wider-blast-radius incident.
#     """
#     delay_days = delay_days or random.randint(3, 8)
#     active = (
#         db.query(Shipment)
#         .filter(Shipment.company_id == company_id, Shipment.status.in_([ShipmentStatus.SCHEDULED, ShipmentStatus.IN_TRANSIT]))
#         .all()
#     )
#     if not active:
#         return {"event": "LOGISTICS_DISRUPTION", "error": "no active shipments to disrupt"}

#     sample_size = max(1, int(len(active) * affected_fraction))
#     affected = random.sample(active, sample_size)
#     for shipment in affected:
#         shipment.delay_days += delay_days
#         shipment.expected_delivery += timedelta(days=delay_days)
#         shipment.status = ShipmentStatus.DELAYED
#     db.commit()

#     return {
#         "event": "LOGISTICS_DISRUPTION",
#         "delay_days": delay_days,
#         "shipments_affected": [str(s.id) for s in affected],
#         "shipments_affected_count": len(affected),
#     }


# def trigger_warehouse_unavailable(db, company_id, warehouse_id: uuid.UUID | None = None, delay_days: int | None = None) -> dict:
#     """
#     A warehouse going offline (fire, system outage, labor issue). There's
#     no `is_operational` column on Warehouse yet -- adding one is a small
#     follow-up migration if this needs to be queried directly later. For
#     now we approximate the operational impact the way it actually
#     matters to the business: every shipment scheduled into that
#     warehouse gets delayed.
#     """
#     warehouse = db.get(Warehouse, warehouse_id) if warehouse_id else (
#         random.choice(db.query(Warehouse).filter(Warehouse.company_id == company_id).all())
#     )
#     if warehouse is None:
#         return {"event": "WAREHOUSE_UNAVAILABLE", "error": "no warehouse available"}

#     delay_days = delay_days or random.randint(2, 5)
#     affected = (
#         db.query(Shipment)
#         .filter(
#             Shipment.company_id == company_id,
#             Shipment.warehouse_id == warehouse.id,
#             Shipment.status.in_([ShipmentStatus.SCHEDULED, ShipmentStatus.IN_TRANSIT]),
#         )
#         .all()
#     )
#     for shipment in affected:
#         shipment.delay_days += delay_days
#         shipment.expected_delivery += timedelta(days=delay_days)
#         shipment.status = ShipmentStatus.DELAYED
#     db.commit()

#     return {
#         "event": "WAREHOUSE_UNAVAILABLE",
#         "warehouse_id": str(warehouse.id),
#         "warehouse_name": warehouse.name,
#         "delay_days": delay_days,
#         "shipments_affected": [str(s.id) for s in affected],
#     }


# EVENT_REGISTRY = {
#     "SHIPMENT_DELAY": trigger_shipment_delay,
#     "SUPPLIER_DELAY": trigger_supplier_delay,
#     "DEMAND_SPIKE": trigger_demand_spike,
#     "INVENTORY_SHORTAGE": trigger_inventory_shortage,
#     "LOGISTICS_DISRUPTION": trigger_logistics_disruption,
#     "WAREHOUSE_UNAVAILABLE": trigger_warehouse_unavailable,
# }