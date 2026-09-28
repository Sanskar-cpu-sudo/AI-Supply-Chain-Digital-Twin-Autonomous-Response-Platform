"""
Full ingestion pipeline: file -> extract text -> chunk -> embed -> store.
Kept as a single function with the embedding step injected as a
parameter (embed_fn) specifically so it can be tested with a fake
embedding function without needing the real model downloaded -- see
Phase 14's test notes for why that matters in this sandbox.
"""
from app.models.document import Document, DocumentChunk
from app.rag.chunking import chunk_text
from app.rag.embeddings import embed_texts
from app.rag.pdf_extraction import extract_text_from_pdf


def ingest_document(
    db, company_id, file_path: str, title: str, doc_type, embed_fn=embed_texts,
    chunk_size: int = 200, overlap: int = 40,
) -> Document:
    """
    Creates one Document row and N DocumentChunk rows (one per chunk,
    each with its own embedding). Raises if the file has no extractable
    text at all (e.g. a scanned PDF with no OCR) rather than silently
    creating a Document with zero searchable chunks.
    """
    if file_path.lower().endswith(".pdf"):
        text = extract_text_from_pdf(file_path)
    else:
        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()

    chunks = chunk_text(text, chunk_size=chunk_size, overlap=overlap)
    if not chunks:
        raise ValueError(
            f"No extractable text found in {file_path}. If this is a scanned/image-only "
            f"PDF, it needs OCR before it can be ingested -- not currently supported."
        )

    embeddings = embed_fn(chunks)
    if len(embeddings) != len(chunks):
        raise RuntimeError(f"Embedding count ({len(embeddings)}) doesn't match chunk count ({len(chunks)})")

    document = Document(company_id=company_id, title=title, doc_type=doc_type, file_path=file_path)
    db.add(document)
    db.flush()

    for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        db.add(
            DocumentChunk(
                company_id=company_id,
                document_id=document.id,
                chunk_index=i,
                content=chunk,
                embedding=embedding,
            )
        )

    db.commit()
    db.refresh(document)
    return document