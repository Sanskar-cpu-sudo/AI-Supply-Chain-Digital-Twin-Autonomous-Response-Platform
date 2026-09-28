"""
Placeholder for the RAG-backed document search tool. Real pgvector
similarity search lands in Phase 14 -- until then this returns a
structured "not yet available" response so the Investigation Agent
gets a clean, informative failure instead of a crash if it tries to
call this tool early.
"""

"""
RAG-backed document search tool for the Investigation/Decision agents.
Real implementation landed in Phase 14.
"""
from app.rag.retrieval import search_documents


def search_company_documents(db, company_id, query: str) -> dict:
    """Search company policy/contract documents for relevant context."""
    results = search_documents(db, company_id, query, top_k=3)
    if not results:
        return {
            "results": [],
            "note": "No matching documents found. Either nothing relevant has been "
            "uploaded, or this company has no documents ingested yet.",
        }
    return {"results": results}
def search_company_documents(db, company_id, query: str) -> dict:
    """Search company policy/contract documents for relevant context. NOT YET IMPLEMENTED (Phase 14)."""
    return {
        "error": "Document search is not yet available (lands in Phase 14 -- RAG/company knowledge). "
        "Do not assume any policy details; note this as a gap in your evidence instead."
    }