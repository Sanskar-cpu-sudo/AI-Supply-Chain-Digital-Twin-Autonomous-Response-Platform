"""Central place for every status/type enum used across the schema."""
import enum


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    MANAGER = "manager"


class OrderStatus(str, enum.Enum):
    PENDING = "pending"
    FULFILLED = "fulfilled"
    AT_RISK = "at_risk"
    CANCELLED = "cancelled"


class ShipmentStatus(str, enum.Enum):
    SCHEDULED = "scheduled"
    IN_TRANSIT = "in_transit"
    DELAYED = "delayed"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class IncidentType(str, enum.Enum):
    SHIPMENT_DELAY = "shipment_delay"
    SUPPLIER_DELAY = "supplier_delay"
    INVENTORY_SHORTAGE = "inventory_shortage"
    DEMAND_SPIKE = "demand_spike"
    LOGISTICS_DISRUPTION = "logistics_disruption"


class IncidentSeverity(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IncidentStatus(str, enum.Enum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    RECOMMENDED = "recommended"
    APPROVED = "approved"
    RESOLVED = "resolved"
    ESCALATED = "escalated"          # hit max re-investigation loops -> human


class InvestigationStatus(str, enum.Enum):
    COMPLETED = "completed"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"   # agent abstained
    FAILED = "failed"                                  # hit guardrail (timeout/max steps)


class RecommendationStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ActionStatus(str, enum.Enum):
    PENDING = "pending"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


class VerificationResult(str, enum.Enum):
    SUCCESS = "success"
    FAILED = "failed"
    PENDING = "pending"


class DocumentType(str, enum.Enum):
    SUPPLIER_CONTRACT = "supplier_contract"
    PROCUREMENT_POLICY = "procurement_policy"
    SHIPPING_POLICY = "shipping_policy"
    WAREHOUSE_POLICY = "warehouse_policy"
    SUPPLIER_AGREEMENT = "supplier_agreement"


class ActorType(str, enum.Enum):
    USER = "user"
    SYSTEM = "system"
    AGENT = "agent"