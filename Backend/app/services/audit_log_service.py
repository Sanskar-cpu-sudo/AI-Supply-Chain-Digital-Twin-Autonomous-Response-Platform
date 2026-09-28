"""
Shared helper so every part of the system logs audit events the same
way. Does NOT commit -- callers add this to their existing transaction
and commit when they're done with their own unit of work, so a failed
step doesn't leave an orphaned "event happened" log entry for something
that actually got rolled back.
"""
from app.models.audit_log import AuditLog


def log_event(db, company_id, incident_id, actor_type, event_type: str, message: str, meta: dict | None = None):
    entry = AuditLog(
        company_id=company_id,
        incident_id=incident_id,
        actor_type=actor_type,
        event_type=event_type,
        message=message,
        meta=meta,
    )
    db.add(entry)
    return entry