"""Plain-text extraction from uploaded client reference documents."""
from pathlib import Path

from pypdf import PdfReader
from docx import Document


def extract_pdf(path: str) -> str:
    reader = PdfReader(path)
    return "\n\n".join(page.extract_text() or "" for page in reader.pages).strip()


def extract_docx(path: str) -> str:
    doc = Document(path)
    return "\n".join(p.text for p in doc.paragraphs).strip()


def extract_txt(path: str) -> str:
    return Path(path).read_text(errors="ignore").strip()


EXTRACTORS = {".pdf": extract_pdf, ".docx": extract_docx, ".txt": extract_txt}


def extract_text(path: str) -> str:
    ext = Path(path).suffix.lower()
    extractor = EXTRACTORS.get(ext)
    if not extractor:
        raise ValueError(f"unsupported file type: {ext}")
    return extractor(path)
