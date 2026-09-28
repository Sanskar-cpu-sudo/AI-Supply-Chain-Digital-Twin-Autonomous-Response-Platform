from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database.session import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check():
    """
    Basic liveness check. React (and later, load balancers / uptime
    monitors) hit this to confirm the API is up and can reach nothing
    more than itself -- deliberately no DB call here, so this endpoint
    stays fast and reliable even if Postgres/Redis are having issues.
    """
    return {"status": "ok"}


@router.get("/health/ready")
def readiness_check(db: Session = Depends(get_db)):
    """
    Readiness check: confirms the API can actually reach Postgres.
    Use this one in Docker healthchecks / deploy pipelines (Phase 26-27)
    where you want to know the whole stack is usable, not just that the
    process is running.
    """
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}