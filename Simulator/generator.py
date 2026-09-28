"""
Generates a realistic baseline supply chain for a company: suppliers,
products, warehouses, inventory levels, and a history of orders +
already-delivered shipments. Call this once per company before running
any event scenarios -- events.py assumes this data already exists.
"""
import random
from datetime import datetime, timedelta, timezone

from app.models.company import Company
from app.models.master_data import Product, Supplier, Warehouse
from app.models.operations import Inventory, Order, Shipment
from app.models.enums import OrderStatus, ShipmentStatus

SUPPLIER_NAMES = ["Northwind Components", "Pacific Rim Metals", "Delta Fabrication", "Summit Logistics Co"]
PRODUCT_CATALOG = [
    ("WIDGET-001", "Blue Widget", 12.50),
    ("WIDGET-002", "Red Widget", 14.00),
    ("GEAR-100", "Steel Gear 100mm", 8.75),
    ("BRACKET-A", "L-Bracket Assembly", 3.20),
    ("MOTOR-SM", "Small DC Motor", 22.00),
]
WAREHOUSE_LOCATIONS = [("Central DC", "Columbus, OH"), ("West Coast Hub", "Reno, NV")]


def generate_baseline(db, company_id, num_historical_orders: int = 20, num_active_shipments: int = 8) -> dict:
    """
    Idempotent-ish: if suppliers/products/warehouses already exist for
    this company, reuses them rather than duplicating. Returns a summary
    dict of what exists after running, for printing/logging.
    """
    suppliers = _get_or_create_suppliers(db, company_id)
    products = _get_or_create_products(db, company_id)
    warehouses = _get_or_create_warehouses(db, company_id)
    inventory = _get_or_create_inventory(db, company_id, products, warehouses)
    orders, shipments = _generate_history(db, company_id, suppliers, products, warehouses, num_historical_orders)
    active_shipments = _generate_active_shipments(db, company_id, suppliers, products, warehouses, num_active_shipments)

    db.commit()
    return {
        "suppliers": len(suppliers),
        "products": len(products),
        "warehouses": len(warehouses),
        "inventory_rows": len(inventory),
        "historical_orders": len(orders),
        "historical_shipments": len(shipments),
        "active_shipments": len(active_shipments),
    }


def _get_or_create_suppliers(db, company_id):
    existing = db.query(Supplier).filter(Supplier.company_id == company_id).all()
    if existing:
        return existing
    suppliers = [
        Supplier(
            company_id=company_id,
            name=name,
            contact_email=f"sales@{name.lower().replace(' ', '')}.com",
            reliability_score=round(random.uniform(0.75, 0.98), 2),
            is_approved=True,
        )
        for name in SUPPLIER_NAMES
    ]
    db.add_all(suppliers)
    db.flush()
    return suppliers


def _get_or_create_products(db, company_id):
    existing = db.query(Product).filter(Product.company_id == company_id).all()
    if existing:
        return existing
    products = [
        Product(company_id=company_id, sku=sku, name=name, unit_cost=cost)
        for sku, name, cost in PRODUCT_CATALOG
    ]
    db.add_all(products)
    db.flush()
    return products


def _get_or_create_warehouses(db, company_id):
    existing = db.query(Warehouse).filter(Warehouse.company_id == company_id).all()
    if existing:
        return existing
    warehouses = [
        Warehouse(company_id=company_id, name=name, location=loc, capacity=random.randint(30000, 80000))
        for name, loc in WAREHOUSE_LOCATIONS
    ]
    db.add_all(warehouses)
    db.flush()
    return warehouses


def _get_or_create_inventory(db, company_id, products, warehouses):
    existing = db.query(Inventory).filter(Inventory.company_id == company_id).all()
    if existing:
        return existing
    rows = []
    for product in products:
        for warehouse in warehouses:
            qty = random.randint(300, 1200)
            rows.append(
                Inventory(
                    company_id=company_id,
                    product_id=product.id,
                    warehouse_id=warehouse.id,
                    quantity_on_hand=qty,
                    reorder_point=int(qty * 0.3),
                    safety_stock=int(qty * 0.15),
                )
            )
    db.add_all(rows)
    db.flush()
    return rows


def _generate_history(db, company_id, suppliers, products, warehouses, num_orders):
    """
    Creates past orders that are already fulfilled, with matching delivered
    shipments -- gives the system a plausible-looking history rather than
    starting from a completely blank slate.
    """
    orders, shipments = [], []
    now = datetime.now(timezone.utc)

    for _ in range(num_orders):
        product = random.choice(products)
        warehouse = random.choice(warehouses)
        supplier = random.choice(suppliers)
        days_ago = random.randint(5, 60)
        requested_date = (now - timedelta(days=days_ago)).date()

        order = Order(
            company_id=company_id,
            customer_name=random.choice(
                ["Big Retailer Inc", "Metro Distribution", "Value Mart", "Regional Supply Co"]
            ),
            product_id=product.id,
            quantity=random.randint(50, 800),
            status=OrderStatus.FULFILLED,
            requested_date=requested_date,
            promised_date=requested_date + timedelta(days=7),
        )
        db.add(order)
        db.flush()
        orders.append(order)

        expected = now - timedelta(days=days_ago - 5)
        shipment = Shipment(
            company_id=company_id,
            supplier_id=supplier.id,
            product_id=product.id,
            warehouse_id=warehouse.id,
            order_id=order.id,
            quantity=order.quantity,
            status=ShipmentStatus.DELIVERED,
            expected_delivery=expected,
            actual_delivery=expected,
            delay_days=0,
        )
        db.add(shipment)
        shipments.append(shipment)

    db.flush()
    return orders, shipments


def _generate_active_shipments(db, company_id, suppliers, products, warehouses, num_shipments):
    """
    Creates shipments that are currently SCHEDULED or IN_TRANSIT (i.e.
    still "live" in the pipeline) with no associated order yet -- these
    are what the event injector (events.py) and later Monitoring (Phase 9)
    actually operate on. Without these, a freshly-seeded company has zero
    shipments an event can act on. Skips generation if active shipments
    already exist, consistent with the other _get_or_create_* functions.
    """
    existing = (
        db.query(Shipment)
        .filter(
            Shipment.company_id == company_id,
            Shipment.status.in_([ShipmentStatus.SCHEDULED, ShipmentStatus.IN_TRANSIT]),
        )
        .all()
    )
    if existing:
        return existing

    shipments = []
    now = datetime.now(timezone.utc)
    for _ in range(num_shipments):
        product = random.choice(products)
        warehouse = random.choice(warehouses)
        supplier = random.choice(suppliers)
        days_out = random.randint(1, 10)
        status = random.choice([ShipmentStatus.SCHEDULED, ShipmentStatus.IN_TRANSIT])

        shipment = Shipment(
            company_id=company_id,
            supplier_id=supplier.id,
            product_id=product.id,
            warehouse_id=warehouse.id,
            order_id=None,
            quantity=random.randint(100, 600),
            status=status,
            expected_delivery=now + timedelta(days=days_out),
            actual_delivery=None,
            delay_days=0,
        )
        db.add(shipment)
        shipments.append(shipment)

    db.flush()
    return shipments


def get_or_create_demo_company(db, name: str = "Demo Company") -> Company:
    company = db.query(Company).filter(Company.name == name).first()
    if company is None:
        company = Company(name=name)
        db.add(company)
        db.commit()
        db.refresh(company)
    return company