from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models.audit_log import AuditLog
from app.models.enums import ActorType, IncidentSeverity, IncidentStatus, IncidentType, ShipmentStatus
from app.models.incident import Incident
from app.models.operations import Inventory, Order, Shipment

OPEN_STATUSES = [IncidentStatus.OPEN, IncidentStatus.INVESTIGATING, IncidentStatus.RECOMMENDED, IncidentStatus.APPROVED]
DEMAND_SPIKE_MULTIPLIER = 1.8
SUPPLIER_DELAY_THRESHOLD = 2
LOGISTICS_DISRUPTION_THRESHOLD = 3


def _has_open_incident(db, company_id, **filters):
    q = db.query(Incident).filter(Incident.company_id == company_id, Incident.status.in_(OPEN_STATUSES))
    for field, value in filters.items():
        q = q.filter(getattr(Incident, field) == value)
    return db.query(q.exists()).scalar()


def _log_detection(db, incident, message):
    db.add(AuditLog(company_id=incident.company_id, incident_id=incident.id, actor_type=ActorType.SYSTEM,
                     event_type="incident_detected", message=message))


def _shipment_severity(delay_days):
    if delay_days >= 7: return IncidentSeverity.CRITICAL
    if delay_days >= 4: return IncidentSeverity.HIGH
    if delay_days >= 2: return IncidentSeverity.MEDIUM
    return IncidentSeverity.LOW


def _inventory_severity(quantity_on_hand, reorder_point, safety_stock):
    if quantity_on_hand <= 0: return IncidentSeverity.CRITICAL
    if quantity_on_hand < safety_stock: return IncidentSeverity.HIGH
    if quantity_on_hand < reorder_point * 0.5: return IncidentSeverity.MEDIUM
    return IncidentSeverity.LOW


def check_supplier_delays(db: Session, company_id):
    created = []
    covered_shipment_ids = set()
    delayed = db.query(Shipment).filter(Shipment.company_id == company_id, Shipment.status == ShipmentStatus.DELAYED).all()
    by_supplier = {}
    for shipment in delayed:
        by_supplier.setdefault(shipment.supplier_id, []).append(shipment)
    for supplier_id, shipments in by_supplier.items():
        if len(shipments) < SUPPLIER_DELAY_THRESHOLD:
            continue
        if _has_open_incident(db, company_id, type=IncidentType.SUPPLIER_DELAY, supplier_id=supplier_id):
            covered_shipment_ids.update(s.id for s in shipments)
            continue
        max_delay = max(s.delay_days for s in shipments)
        representative_shipment = max(shipments, key=lambda s: s.delay_days)  # most-delayed one, so
        # downstream action handlers (expedite_shipment, use_backup_supplier) have a concrete shipment
        # to act on -- without this, a SUPPLIER_DELAY incident had no shipment_id at all, and neither
        # the baseline rule nor the AI system's handlers could execute anything for it. Caught via
        # Phase 24's eval harness: both branches failed this incident type identically.
        incident = Incident(company_id=company_id, type=IncidentType.SUPPLIER_DELAY, severity=_shipment_severity(max_delay),
                             supplier_id=supplier_id, shipment_id=representative_shipment.id, product_id=representative_shipment.product_id,
                             warehouse_id=representative_shipment.warehouse_id,
                             description=f"{len(shipments)} shipments from this supplier are delayed (up to {max_delay} days).")
        db.add(incident); db.flush()
        _log_detection(db, incident, f"Supplier delay detected: {len(shipments)} shipments affected, max delay {max_delay} days")
        created.append(incident)
        covered_shipment_ids.update(s.id for s in shipments)
    return created, covered_shipment_ids


def check_logistics_disruptions(db: Session, company_id, exclude_shipment_ids: set):
    delayed = db.query(Shipment).filter(Shipment.company_id == company_id, Shipment.status == ShipmentStatus.DELAYED,
                                         ~Shipment.id.in_(exclude_shipment_ids) if exclude_shipment_ids else True).all()
    if len(delayed) < LOGISTICS_DISRUPTION_THRESHOLD:
        return [], set()
    if _has_open_incident(db, company_id, type=IncidentType.LOGISTICS_DISRUPTION):
        return [], {s.id for s in delayed}
    max_delay = max(s.delay_days for s in delayed)
    supplier_count = len({s.supplier_id for s in delayed})
    warehouse_count = len({s.warehouse_id for s in delayed})
    incident = Incident(company_id=company_id, type=IncidentType.LOGISTICS_DISRUPTION, severity=_shipment_severity(max_delay),
                         description=f"{len(delayed)} shipments delayed at once across {supplier_count} supplier(s) and {warehouse_count} warehouse(s) (up to {max_delay} days).")
    db.add(incident); db.flush()
    _log_detection(db, incident, f"Logistics disruption detected: {len(delayed)} shipments across {supplier_count} suppliers")
    return [incident], {s.id for s in delayed}


def check_shipment_delays(db: Session, company_id, exclude_shipment_ids: set):
    created = []
    delayed = db.query(Shipment).filter(Shipment.company_id == company_id, Shipment.status == ShipmentStatus.DELAYED,
                                         ~Shipment.id.in_(exclude_shipment_ids) if exclude_shipment_ids else True).all()
    for shipment in delayed:
        if _has_open_incident(db, company_id, shipment_id=shipment.id):
            continue
        incident = Incident(company_id=company_id, type=IncidentType.SHIPMENT_DELAY, severity=_shipment_severity(shipment.delay_days),
                             shipment_id=shipment.id, supplier_id=shipment.supplier_id, product_id=shipment.product_id,
                             warehouse_id=shipment.warehouse_id,
                             description=f"Shipment delayed by {shipment.delay_days} days (now expected {shipment.expected_delivery.date()}).")
        db.add(incident); db.flush()
        _log_detection(db, incident, f"Shipment delay detected: {shipment.delay_days} days")
        created.append(incident)
    return created


def check_inventory_shortages(db: Session, company_id):
    created = []
    rows = db.query(Inventory).filter(Inventory.company_id == company_id).all()
    for row in rows:
        if row.quantity_on_hand >= row.reorder_point:
            continue
        if _has_open_incident(db, company_id, product_id=row.product_id, warehouse_id=row.warehouse_id, type=IncidentType.INVENTORY_SHORTAGE):
            continue
        incident = Incident(company_id=company_id, type=IncidentType.INVENTORY_SHORTAGE,
                             severity=_inventory_severity(row.quantity_on_hand, row.reorder_point, row.safety_stock),
                             product_id=row.product_id, warehouse_id=row.warehouse_id,
                             description=f"Stock at {row.quantity_on_hand} units, below reorder point of {row.reorder_point}.")
        db.add(incident); db.flush()
        _log_detection(db, incident, f"Inventory shortage detected: {row.quantity_on_hand} on hand, reorder point {row.reorder_point}")
        created.append(incident)
    return created


def check_demand_spikes(db: Session, company_id):
    created = []
    products_with_pending = db.query(Order.product_id).filter(Order.company_id == company_id).distinct().all()
    for (product_id,) in products_with_pending:
        all_orders = db.query(Order).filter(Order.company_id == company_id, Order.product_id == product_id).all()
        if len(all_orders) < 3:
            continue
        avg_qty = sum(o.quantity for o in all_orders) / len(all_orders)
        pending = [o for o in all_orders if o.quantity >= avg_qty * DEMAND_SPIKE_MULTIPLIER]
        for order in pending:
            if _has_open_incident(db, company_id, product_id=product_id, type=IncidentType.DEMAND_SPIKE):
                continue
            incident = Incident(company_id=company_id, type=IncidentType.DEMAND_SPIKE,
                                 severity=IncidentSeverity.MEDIUM if order.quantity < avg_qty * 2.5 else IncidentSeverity.HIGH,
                                 product_id=product_id,
                                 description=f"Order for {order.quantity} units is {order.quantity / avg_qty:.1f}x the historical average of {avg_qty:.0f} units for this product.")
            db.add(incident); db.flush()
            _log_detection(db, incident, f"Demand spike detected: order qty {order.quantity} vs avg {avg_qty:.0f}")
            created.append(incident)
    return created


def run_all_checks(db: Session, company_id) -> dict:
    supplier_incidents, covered_by_supplier = check_supplier_delays(db, company_id)
    logistics_incidents, covered_by_logistics = check_logistics_disruptions(db, company_id, exclude_shipment_ids=covered_by_supplier)
    shipment_incidents = check_shipment_delays(db, company_id, exclude_shipment_ids=covered_by_supplier | covered_by_logistics)
    inventory_incidents = check_inventory_shortages(db, company_id)
    demand_incidents = check_demand_spikes(db, company_id)
    db.commit()
    all_created = supplier_incidents + logistics_incidents + shipment_incidents + inventory_incidents + demand_incidents
    for incident in all_created:
        db.refresh(incident)  # ensure created_at etc are populated post-commit for the caller to broadcast
    return {
        "supplier_delay_incidents": len(supplier_incidents),
        "logistics_disruption_incidents": len(logistics_incidents),
        "shipment_delay_incidents": len(shipment_incidents),
        "inventory_shortage_incidents": len(inventory_incidents),
        "demand_spike_incidents": len(demand_incidents),
        "total_incidents_created": len(all_created),
        "created_incidents": all_created,  # raw Incident objects -- Phase 22's WebSocket broadcast uses these
    }