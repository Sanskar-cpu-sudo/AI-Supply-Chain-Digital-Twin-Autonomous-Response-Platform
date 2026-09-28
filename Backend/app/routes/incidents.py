import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database.session import get_db
from app.models.audit_log import AuditLog
from app.models.company import User
from app.models.enums import ActorType, IncidentSeverity, IncidentStatus, IncidentType, InvestigationStatus
from app.models.incident import Incident
from app.models.investigation import Investigation
from app.agents.investigation import run_investigation
from app.services.recommendation_service import RecommendationError, generate_recommendation
from app.schemas.incident import IncidentInvestigateResponse, IncidentOut, InvestigationOut, RecommendationOut, TimelineEntryOut
from app.services.deps import get_current_user

router = APIRouter(prefix="/incidents", tags=["incidents"])


@router.get("", response_model=list[IncidentOut])
def list_incidents(status_filter: IncidentStatus | None = Query(default=None, alias="status"),
                    severity: IncidentSeverity | None = Query(default=None), type_: IncidentType | None = Query(default=None, alias="type"),
                    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    q = db.query(Incident).filter(Incident.company_id == current_user.company_id)
    if status_filter: q = q.filter(Incident.status == status_filter)
    if severity: q = q.filter(Incident.severity == severity)
    if type_: q = q.filter(Incident.type == type_)
    return q.order_by(Incident.created_at.desc()).all()


@router.get("/{incident_id}", response_model=IncidentOut)
def get_incident(incident_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    incident = db.query(Incident).filter(Incident.id == incident_id, Incident.company_id == current_user.company_id).first()
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident


@router.get("/{incident_id}/investigations", response_model=list[InvestigationOut])
def list_investigations(incident_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    incident = db.query(Incident).filter(Incident.id == incident_id, Incident.company_id == current_user.company_id).first()
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident.investigations


@router.post("/{incident_id}/investigate", response_model=IncidentInvestigateResponse)
def investigate_incident(incident_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    incident = db.query(Incident).filter(Incident.id == incident_id, Incident.company_id == current_user.company_id).first()
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    if incident.status != IncidentStatus.OPEN:
        raise HTTPException(status_code=400, detail=f"Incident is already '{incident.status.value}' -- can only start investigation on an OPEN incident.")
    incident.status = IncidentStatus.INVESTIGATING
    db.add(AuditLog(company_id=current_user.company_id, incident_id=incident.id, actor_type=ActorType.USER,
                     actor_id=current_user.id, event_type="investigation_started",
                     message=f"Investigation manually triggered by {current_user.full_name}."))
    db.commit(); db.refresh(incident)
    investigation = run_investigation(db, current_user.company_id, incident)
    if investigation.status == InvestigationStatus.COMPLETED:
        message = f"Investigation complete. Root cause: {investigation.root_cause}"
    elif investigation.status == InvestigationStatus.INSUFFICIENT_EVIDENCE:
        message = "Investigation complete, but evidence was insufficient. Human review required."
    else:
        message = "Investigation failed to complete. See audit log for details."
    return IncidentInvestigateResponse(id=incident.id, status=incident.status, message=message)


@router.get("/{incident_id}/recommendations", response_model=list[RecommendationOut])
def list_recommendations(incident_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    incident = db.query(Incident).filter(Incident.id == incident_id, Incident.company_id == current_user.company_id).first()
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident.recommendations


@router.post("/{incident_id}/recommend", response_model=RecommendationOut)
def recommend_for_incident(incident_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    incident = db.query(Incident).filter(Incident.id == incident_id, Incident.company_id == current_user.company_id).first()
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    investigation = (db.query(Investigation).filter(Investigation.incident_id == incident.id, Investigation.status == InvestigationStatus.COMPLETED)
                      .order_by(Investigation.created_at.desc()).first())
    if investigation is None:
        raise HTTPException(status_code=400, detail="No completed investigation found for this incident. Run POST /investigate first.")
    try:
        recommendation = generate_recommendation(db, current_user.company_id, incident, investigation)
    except RecommendationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return recommendation


@router.get("/{incident_id}/timeline", response_model=list[TimelineEntryOut])
def get_incident_timeline(incident_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Full chronological audit trail for one incident -- every detection,
    LLM call, individual tool call, agent completion, human approval/
    rejection, action execution, and verification, oldest first. This is
    the plan's own example (09:31 Incident detected, 09:31 getShipment(),
    ...) made queryable.
    """
    incident = db.query(Incident).filter(Incident.id == incident_id, Incident.company_id == current_user.company_id).first()
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return (
        db.query(AuditLog)
        .filter(AuditLog.incident_id == incident.id, AuditLog.company_id == current_user.company_id)
        .order_by(AuditLog.created_at.asc())
        .all()
    )