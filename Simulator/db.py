"""
Gives the simulator a DB session using the exact same models as the
backend, so data it writes is 100% compatible with what the API and
agents expect -- no separate schema to keep in sync.
"""
import os
import sys

# ai-supply-chain/simulator/db.py -> need ai-supply-chain/backend on sys.path
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from app.database.session import SessionLocal  # noqa: E402
import app.models  # noqa: E402  (registers all models on Base.metadata)


def get_session():
    """Caller is responsible for closing this (use as a context manager
    via `with get_session() as db:` since SQLAlchemy Sessions support that)."""
    return SessionLocal()