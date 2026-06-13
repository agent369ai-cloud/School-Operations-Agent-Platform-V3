"""
Extract plain text from an uploaded document.

Supported in this cut: plain text, PDF (pdfplumber), DOCX (python-docx).
Raises ValueError on an unreadable/corrupt file so the route can return 400.
"""

from __future__ import annotations

import io

PDF_TYPES = {"application/pdf"}
DOCX_TYPES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def extract_text(data: bytes, filename: str | None, content_type: str | None) -> str:
    name = (filename or "").lower()
    ct = (content_type or "").lower()

    try:
        if name.endswith(".pdf") or ct in PDF_TYPES:
            return _from_pdf(data)
        if name.endswith(".docx") or ct in DOCX_TYPES:
            return _from_docx(data)
        # default: treat as UTF-8 text
        return data.decode("utf-8", errors="replace").strip()
    except ValueError:
        raise
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"Could not read document: {e}") from e


def _from_pdf(data: bytes) -> str:
    import pdfplumber  # lazy import; heavy
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        pages = [(p.extract_text() or "") for p in pdf.pages]
    text = "\n".join(pages).strip()
    if not text:
        raise ValueError("PDF contained no extractable text (may be scanned; OCR not enabled)")
    return text


def _from_docx(data: bytes) -> str:
    from docx import Document as Docx  # lazy import
    doc = Docx(io.BytesIO(data))
    text = "\n".join(p.text for p in doc.paragraphs).strip()
    if not text:
        raise ValueError("DOCX contained no text")
    return text
