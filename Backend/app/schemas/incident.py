import uuid
from datetime import datetime
from pydantic import BaseModel
from app.models.enums import IncidentSeverity, IncidentStatus, IncidentType, InvestigationStatus, RecommendationStatus


class IncidentOut(BaseModel):
    id: uuid.UUID
    type: IncidentType
    severity: IncidentSeverity
    status: IncidentStatus
    description: str | None
    shipment_id: uuid.UUID | None
    supplier_id: uuid.UUID | None
    product_id: uuid.UUID | None
    warehouse_id: uuid.UUID | None
    reinvestigation_count: int
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class IncidentInvestigateResponse(BaseModel):
    id: uuid.UUID
    status: IncidentStatus
    message: str


class InvestigationOut(BaseModel):
    id: uuid.UUID
    status: InvestigationStatus
    root_cause: str | None
    evidence: list | None
    impact: dict | None
    confidence: float | None
    tool_calls: list | None
    created_at: datetime
    model_config = {"from_attributes": True}


class RecommendationOut(BaseModel):
    id: uuid.UUID
    option_chosen: str
    options_considered: list
    estimated_cost: float | None
    expected_delay_days: int | None
    stockout_risk: str | None
    reasoning: str | None
    confidence: float | None
    status: RecommendationStatus
    created_at: datetime
    model_config = {"from_attributes": True}


class TimelineEntryOut(BaseModel):
    id: uuid.UUID
    actor_type: str
    event_type: str
    message: str
    meta: dict | None
    created_at: datetime
    model_config = {"from_attributes": True}