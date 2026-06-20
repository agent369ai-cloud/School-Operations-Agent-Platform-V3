"""
Document text extraction.

Turns raw uploaded bytes into plain text the parser can reason over. Supports
PDF, DOCX, CSV/TSV, plain text, and images (OCR when a backend is available).

Security: extraction NEVER executes content. Extracted text is later passed to
the model strictly as delimited, untrusted data (see ``injection.py``).
"""
from __future__ import annotations

import csv
import io
from pathlib import Path

from app.core.logging import get_logger

log = get_logger("extract")


class ExtractionError(Exception):
    pass


def extract_text(*, data: bytes, filename: str, content_type: str | None = None) -> str:
    suffix = Path(filename).suffix.lower()
    try:
        if suffix == ".pdf":
            return _extract_pdf(data)
        if suffix == ".docx":
            return _extract_docx(data)
        if suffix in (".csv", ".tsv"):
            return _normalize_csv(data, delimiter="\t" if suffix == ".tsv" else ",")
        if suffix in (".png", ".jpg", ".jpeg"):
            return _extract_image_ocr(data)
        # txt and everything else: best-effort utf-8.
        return data.decode("utf-8", errors="replace")
    except ExtractionError:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise ExtractionError(f"failed to extract {filename}: {exc}") from exc


def _extract_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise ExtractionError("pypdf not installed") from exc
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages).strip()


def _extract_docx(data: bytes) -> str:
    try:
        import docx  # python-docx
    except ImportError as exc:  # pragma: no cover
        raise ExtractionError("python-docx not installed") from exc
    document = docx.Document(io.BytesIO(data))
    return "\n".join(p.text for p in document.paragraphs).strip()


def _normalize_csv(data: bytes, *, delimiter: str = ",") -> str:
    """Re-emit CSV as clean, comma-separated lines so the roster parser sees a
    predictable shape regardless of the source dialect."""
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    out_lines = []
    for row in reader:
        out_lines.append(",".join(cell.strip() for cell in row))
    return "\n".join(out_lines).strip()


def _extract_image_ocr(data: bytes) -> str:
    """OCR via pytesseract if available; otherwise raise a clear error so the
    caller can ask the user to paste text instead. (Bonus feature hook.)"""
    try:
        import pytesseract
        from PIL import Image
    except ImportError as exc:  # pragma: no cover
        raise ExtractionError(
            "OCR backend not installed; paste the text instead"
        ) from exc
    image = Image.open(io.BytesIO(data))
    return pytesseract.image_to_string(image).strip()
