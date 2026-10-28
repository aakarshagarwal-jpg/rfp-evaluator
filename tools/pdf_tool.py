"""Document Tool: extract clean text from a supplier PDF (PyMuPDF)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import pymupdf  # PyMuPDF

MAX_CHARS = 60_000          # keeps prompts inside context limits for 2-10 page proposals
MIN_USEFUL_CHARS = 200      # below this the document is treated as unreadable


class DocumentError(ValueError):
    """Raised when a PDF cannot be used for evaluation."""


@dataclass
class ExtractedDocument:
    file_name: str
    text: str
    page_count: int
    char_count: int
    warnings: list[str] = field(default_factory=list)


def _clean(text: str) -> str:
    text = text.replace("\u00a0", " ").replace("\u00ad", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"-\n(?=[a-z])", "", text)      # re-join hyphenated line breaks
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_text(pdf_bytes: bytes, file_name: str = "document.pdf") -> ExtractedDocument:
    if not pdf_bytes:
        raise DocumentError(f"{file_name}: file is empty.")
    if not pdf_bytes[:1024].lstrip().startswith(b"%PDF"):
        raise DocumentError(f"{file_name}: not a valid PDF file.")
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:  # corrupt file
        raise DocumentError(f"{file_name}: could not be opened ({exc}).") from exc

    warnings: list[str] = []
    if doc.needs_pass:
        raise DocumentError(f"{file_name}: PDF is password-protected.")

    pages = []
    for i, page in enumerate(doc, start=1):
        page_text = page.get_text("text", sort=True)
        if not page_text.strip():
            warnings.append(f"{file_name}: page {i} has no extractable text (scanned image?).")
        pages.append(f"[Page {i}]\n{page_text}")
    page_count = doc.page_count
    doc.close()

    text = _clean("\n\n".join(pages))
    useful = len(re.sub(r"\[Page \d+\]|\s", "", text))
    if useful < MIN_USEFUL_CHARS:
        raise DocumentError(
            f"{file_name}: only {useful} characters of text found. The PDF appears to be blank or "
            "scanned; OCR is out of scope, please upload a text-based PDF.")
    if len(text) > MAX_CHARS:
        warnings.append(f"{file_name}: text truncated from {len(text):,} to {MAX_CHARS:,} characters.")
        text = text[:MAX_CHARS]
    return ExtractedDocument(file_name, text, page_count, len(text), warnings)
