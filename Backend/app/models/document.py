import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDPKMixin, company_fk
from app.models.enums import DocumentType

# Embedding dimension for the model used in Phase 14 (e.g. text-embedding-3-small
# = 1536, or a smaller sentence-transformers model = 384). Change here if the
# embedding model changes -- it drives the pgvector column width below.
# Groq has no embeddings API (LLM inference only), so Phase 14 uses a
# local sentence-transformers model instead of a second paid provider.
# all-MiniLM-L6-v2 produces 384-dim embeddings -- if you swap in a
# different embedding model later (e.g. OpenAI's text-embedding-3-small
# at 1536-dim), this constant AND a new Alembic migration to widen the
# column are both required; existing embeddings would need re-computing
# too, since vectors of different dimensions aren't comparable.
EMBEDDING_DIM = 384


class Document(UUIDPKMixin, TimestampMixin, Base):
    """
    A source file (contract, policy, agreement) uploaded for RAG.
    The raw file lives on disk/object storage; file_path points to it.
    """

    __tablename__ = "documents"

    company_id: Mapped[uuid.UUID] = company_fk()
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    doc_type: Mapped[DocumentType] = mapped_column(Enum(DocumentType, name="document_type"), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)

    chunks: Mapped[list["DocumentChunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class DocumentChunk(UUIDPKMixin, TimestampMixin, Base):
    """
    One embedded chunk of a Document, used by the Investigation/Decision
    agents' search_company_documents() tool (Phase 14) via pgvector
    cosine similarity search.
    """

    __tablename__ = "document_chunks"

    company_id: Mapped[uuid.UUID] = company_fk()
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)

    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)

    document: Mapped["Document"] = relationship(back_populates="chunks")