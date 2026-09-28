import os
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models.company import User
from app.models.document import Document
from app.models.enums import DocumentType
from app.rag.ingestion import ingest_document
from app.services.deps import get_current_user

router = APIRouter(prefix="/documents", tags=["documents"])

# Where uploaded files land before/after ingestion. In Phase 26 (Docker)
# this should be a mounted volume, not a path inside the container image.
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "uploaded_documents")


@router.post("", status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(...),
    doc_type: DocumentType = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Uploads a file, saves it, then runs the full ingestion pipeline
    (extract -> chunk -> embed -> store). Accepts .pdf or .txt.

    NOTE: this makes a real embedding model call (local, but the model
    itself needs to have been downloaded once -- see app/rag/embeddings.py).
    """
    if not (file.filename.lower().endswith(".pdf") or file.filename.lower().endswith(".txt")):
        raise HTTPException(status_code=400, detail="Only .pdf and .txt files are supported.")

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    safe_name = f"{uuid.uuid4()}_{file.filename}"
    file_path = os.path.join(UPLOAD_DIR, safe_name)

    contents = await file.read()
    with open(file_path, "wb") as f:
        f.write(contents)

    try:
        document = ingest_document(db, current_user.company_id, file_path, title, doc_type)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {
        "id": str(document.id),
        "title": document.title,
        "doc_type": document.doc_type.value,
        "chunk_count": len(document.chunks),
    }


@router.get("")
def list_documents(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    documents = db.query(Document).filter(Document.company_id == current_user.company_id).all()
    return [
        {"id": str(d.id), "title": d.title, "doc_type": d.doc_type.value, "chunk_count": len(d.chunks)}
        for d in documents
    ]