"""
Semantic search over a company's ingested documents. embed_fn is
injectable (same reasoning as ingestion.py) so this can be tested with
a fake embedding function without needing the real model.
"""
from app.models.document import Document, DocumentChunk
from app.rag.embeddings import embed_text


def search_documents(db, company_id, query: str, top_k: int = 3, embed_fn=embed_text) -> list[dict]:
    """
    Returns the top_k most semantically similar chunks to `query`, each
    with its source document's title so the agent (and a human reading
    the evidence trail) knows where a fact came from -- not just a bare
    snippet with no citation.
    """
    query_embedding = embed_fn(query)

    results = (
        db.query(DocumentChunk, Document.title)
        .join(Document, DocumentChunk.document_id == Document.id)
        .filter(DocumentChunk.company_id == company_id)
        .order_by(DocumentChunk.embedding.cosine_distance(query_embedding))
        .limit(top_k)
        .all()
    )

    return [
        {
            "document_title": title,
            "chunk_index": chunk.chunk_index,
            "content": chunk.content,
        }
        for chunk, title in results
    ]