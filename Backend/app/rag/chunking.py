"""
Splits document text into overlapping chunks before embedding. Overlap
matters: a policy clause that straddles a chunk boundary (e.g. "Supplier
B is approved, but..." / "...minimum order quantity is 300 units.")
should still be findable as one coherent unit, not split with the
condition on one side and the number on the other.

Chunking by word count rather than raw characters keeps chunks roughly
comparable in information density regardless of formatting quirks in
the source PDF (extra whitespace, line breaks mid-sentence, etc).
"""


def chunk_text(text: str, chunk_size: int = 200, overlap: int = 40) -> list[str]:
    """
    chunk_size / overlap are in WORDS, not characters. Defaults chosen to
    keep each chunk small enough for good retrieval precision (a query
    matching a 200-word chunk is more specific than matching a 2000-word
    page) while still containing enough surrounding context to be useful
    on its own once retrieved.
    """
    if chunk_size <= overlap:
        raise ValueError("chunk_size must be greater than overlap, or chunks would never advance")

    words = text.split()
    if not words:
        return []

    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        if end >= len(words):
            break
        start = end - overlap

    return chunks