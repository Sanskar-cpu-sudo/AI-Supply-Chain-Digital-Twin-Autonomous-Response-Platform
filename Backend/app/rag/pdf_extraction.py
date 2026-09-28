"""
Extracts plain text from a PDF for chunking + embedding. Uses pypdf --
lightweight, pure Python, no external binary dependency (unlike some
alternatives that shell out to poppler/ghostscript).

Does NOT handle scanned/image-only PDFs (would need OCR, e.g.
pytesseract) -- that's out of scope for Phase 14's "read our own policy
PDFs" use case, where documents are assumed to be real, selectable text.
If extraction returns suspiciously little text relative to page count,
that's usually the tell that a PDF is actually scanned images.
"""
from pypdf import PdfReader


def extract_text_from_pdf(file_path: str) -> str:
    reader = PdfReader(file_path)
    pages_text = []
    for page in reader.pages:
        text = page.extract_text() or ""
        pages_text.append(text)
    return "\n\n".join(pages_text)