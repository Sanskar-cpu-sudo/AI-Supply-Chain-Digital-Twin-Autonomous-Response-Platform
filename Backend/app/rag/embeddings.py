"""
Local embedding model wrapper. Groq (this project's LLM provider) does
not offer an embeddings API -- rather than add a second paid provider
(e.g. OpenAI) just for embeddings, this uses sentence-transformers
running locally: free, no API key, no per-call latency to an external
service, and good enough quality for searching internal policy/contract
documents (this isn't a general-purpose search engine).

IMPORTANT -- untested in the sandbox this was built in: the first call
to get_embedding_model() downloads the model from huggingface.co, which
that sandbox's network allowlist blocks. The code below is written
correctly against sentence-transformers' documented API, but you should
run test_embedding_model() below once, on your own machine, before
relying on ingestion/search actually working.
"""
from functools import lru_cache

EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"  # 384-dim, matches EMBEDDING_DIM in app/models/document.py


@lru_cache(maxsize=1)
def get_embedding_model():
    """
    Cached so the (somewhat slow) model load only happens once per
    process, not once per request. First call downloads ~80MB from
    huggingface.co if not already cached locally under ~/.cache/torch.
    """
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(EMBEDDING_MODEL_NAME)


def embed_text(text: str) -> list[float]:
    model = get_embedding_model()
    return model.encode(text, normalize_embeddings=True).tolist()


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Batched version -- meaningfully faster than calling embed_text() in
    a loop when ingesting a document with many chunks."""
    model = get_embedding_model()
    return model.encode(texts, normalize_embeddings=True).tolist()


def test_embedding_model() -> dict:
    """
    Run this once on your own machine to confirm the model actually
    downloads and produces embeddings of the expected dimension:

        python -c "from app.rag.embeddings import test_embedding_model; print(test_embedding_model())"
    """
    from app.models.document import EMBEDDING_DIM

    vec = embed_text("This is a test sentence.")
    return {
        "model": EMBEDDING_MODEL_NAME,
        "vector_length": len(vec),
        "expected_length": EMBEDDING_DIM,
        "matches_expected_dimension": len(vec) == EMBEDDING_DIM,
    }