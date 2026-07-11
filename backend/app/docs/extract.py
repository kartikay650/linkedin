"""Plain-text extraction from uploaded client reference documents.

For PDFs we also pull LinkedIn profile URLs out of the link annotations (the
"Viral Accounts" names in a strategy doc are usually hyperlinks). pypdf's plain
text extraction drops those URLs, so we append them as a labelled list — that
gives the LLM the authoritative profile links straight from the client's doc,
instead of us guessing them via search.
"""
import re
from pathlib import Path

from pypdf import PdfReader
from docx import Document

_LINKEDIN_IN = re.compile(r"linkedin\.com/in/", re.I)


def _pdf_linkedin_links(reader: PdfReader) -> list[str]:
    urls = []
    for page in reader.pages:
        annots = page.get("/Annots")
        if not annots:
            continue
        try:
            annots = annots.get_object()
        except Exception:
            continue
        for a in annots:
            try:
                action = a.get_object().get("/A")
                uri = action.get_object().get("/URI") if action else None
                if uri and _LINKEDIN_IN.search(str(uri)):
                    clean = str(uri).split("?")[0].rstrip("/")
                    if clean not in urls:
                        urls.append(clean)
            except Exception:
                continue
    return urls


def extract_pdf(path: str) -> str:
    reader = PdfReader(path)
    text = "\n\n".join(page.extract_text() or "" for page in reader.pages).strip()
    links = _pdf_linkedin_links(reader)
    if links:
        text += "\n\n[LinkedIn profile links referenced in this document]\n" + "\n".join(links)
    return text


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
