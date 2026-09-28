import os, sys
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)
_SIMULATOR_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "simulator"))
if _SIMULATOR_DIR not in sys.path:
    sys.path.insert(0, _SIMULATOR_DIR)
from app.database.session import SessionLocal
import app.models


def get_session():
    return SessionLocal()