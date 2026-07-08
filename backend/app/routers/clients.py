import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.docs.extract import extract_text
from app.docs.youtube import TranscriptUnavailable, extract_youtube_transcript
from app.jobs.discovery import run_discovery_for_client
from app.llm.tone_synthesis import synthesize_tone_profile
from app.models import Burner, Client, ClientDocument, DocumentStatus, DocumentSource, Prospect, ProspectStatus, WatchCreator
from app.schemas import (
    ClientCreate, ClientDocumentOut, ClientOut, ClientUpdate, ProspectOut,
    ToneSynthesisOut, WatchCreatorCreate, WatchCreatorOut, YoutubeDocumentCreate,
)

router = APIRouter(prefix="/clients", tags=["clients"])

ALLOWED_UPLOAD_EXTENSIONS = {".pdf", ".docx", ".txt"}


@router.get("", response_model=list[ClientOut])
def list_clients(db: Session = Depends(get_db)):
    return db.query(Client).all()


@router.post("", response_model=ClientOut)
def create_client(payload: ClientCreate, db: Session = Depends(get_db)):
    if payload.burner_id is not None and not db.get(Burner, payload.burner_id):
        raise HTTPException(400, f"burner {payload.burner_id} not found")

    client = Client(**payload.model_dump())
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


@router.get("/{client_id}", response_model=ClientOut)
def get_client(client_id: int, db: Session = Depends(get_db)):
    client = db.get(Client, client_id)
    if not client:
        raise HTTPException(404, "client not found")
    return client


@router.patch("/{client_id}", response_model=ClientOut)
def update_client(client_id: int, payload: ClientUpdate, db: Session = Depends(get_db)):
    client = db.get(Client, client_id)
    if not client:
        raise HTTPException(404, "client not found")

    updates = payload.model_dump(exclude_unset=True)
    if updates.get("burner_id") is not None and not db.get(Burner, updates["burner_id"]):
        raise HTTPException(400, f"burner {updates['burner_id']} not found")

    for field, value in updates.items():
        setattr(client, field, value)
    db.commit()
    db.refresh(client)
    return client


@router.get("/{client_id}/watch-creators", response_model=list[WatchCreatorOut])
def list_watch_creators(client_id: int, db: Session = Depends(get_db)):
    return db.query(WatchCreator).filter(WatchCreator.client_id == client_id).all()


@router.post("/{client_id}/watch-creators", response_model=WatchCreatorOut)
def add_watch_creator(client_id: int, payload: WatchCreatorCreate, db: Session = Depends(get_db)):
    if not db.get(Client, client_id):
        raise HTTPException(404, "client not found")

    creator = WatchCreator(client_id=client_id, **payload.model_dump())
    db.add(creator)
    db.commit()
    db.refresh(creator)
    return creator


@router.delete("/{client_id}/watch-creators/{creator_id}")
def remove_watch_creator(client_id: int, creator_id: int, db: Session = Depends(get_db)):
    creator = db.get(WatchCreator, creator_id)
    if not creator or creator.client_id != client_id:
        raise HTTPException(404, "watch creator not found")
    db.delete(creator)
    db.commit()
    return {"ok": True}


@router.get("/{client_id}/documents", response_model=list[ClientDocumentOut])
def list_documents(client_id: int, db: Session = Depends(get_db)):
    if not db.get(Client, client_id):
        raise HTTPException(404, "client not found")
    return db.query(ClientDocument).filter(ClientDocument.client_id == client_id).all()


@router.post("/{client_id}/documents/upload", response_model=ClientDocumentOut)
def upload_document(client_id: int, file: UploadFile, db: Session = Depends(get_db)):
    client = db.get(Client, client_id)
    if not client:
        raise HTTPException(404, "client not found")

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(400, f"unsupported file type {ext!r} — allowed: {sorted(ALLOWED_UPLOAD_EXTENSIONS)}")

    contents = file.file.read()
    if len(contents) > settings.max_upload_size_mb * 1024 * 1024:
        raise HTTPException(400, f"file exceeds {settings.max_upload_size_mb}MB limit")

    client_dir = os.path.join(settings.client_docs_dir, str(client_id))
    os.makedirs(client_dir, exist_ok=True)
    storage_path = os.path.join(client_dir, f"{uuid.uuid4().hex}_{file.filename}")
    with open(storage_path, "wb") as f:
        f.write(contents)

    doc = ClientDocument(
        client_id=client_id,
        source_type=DocumentSource.upload,
        original_filename=file.filename,
        storage_path=storage_path,
        status=DocumentStatus.processing,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    try:
        doc.extracted_text = extract_text(storage_path)
        doc.status = DocumentStatus.done
    except Exception as e:
        doc.status = DocumentStatus.failed
        doc.error_detail = str(e)
    db.commit()
    db.refresh(doc)
    return doc


@router.post("/{client_id}/documents/youtube", response_model=ClientDocumentOut)
def add_youtube_document(client_id: int, payload: YoutubeDocumentCreate, db: Session = Depends(get_db)):
    if not db.get(Client, client_id):
        raise HTTPException(404, "client not found")

    doc = ClientDocument(
        client_id=client_id,
        source_type=DocumentSource.youtube,
        source_url=payload.url,
        status=DocumentStatus.processing,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    try:
        doc.extracted_text = extract_youtube_transcript(payload.url)
        doc.status = DocumentStatus.done
    except TranscriptUnavailable as e:
        doc.status = DocumentStatus.failed
        doc.error_detail = str(e)
    db.commit()
    db.refresh(doc)
    return doc


@router.delete("/{client_id}/documents/{doc_id}")
def delete_document(client_id: int, doc_id: int, db: Session = Depends(get_db)):
    doc = db.get(ClientDocument, doc_id)
    if not doc or doc.client_id != client_id:
        raise HTTPException(404, "document not found")
    if doc.storage_path and os.path.exists(doc.storage_path):
        os.remove(doc.storage_path)
    db.delete(doc)
    db.commit()
    return {"ok": True}


@router.post("/{client_id}/tone-synthesis", response_model=ToneSynthesisOut)
def tone_synthesis(client_id: int, db: Session = Depends(get_db)):
    """Proposes a tone_profile from the client's done documents — never saves it.
    A human reviews/edits the proposal and PATCHes the client to actually apply it."""
    client = db.get(Client, client_id)
    if not client:
        raise HTTPException(404, "client not found")

    documents = db.query(ClientDocument).filter(
        ClientDocument.client_id == client_id, ClientDocument.status == DocumentStatus.done
    ).all()
    if not documents:
        raise HTTPException(400, "no successfully-processed documents to synthesize from")

    proposed = synthesize_tone_profile(client, documents)
    return ToneSynthesisOut(proposed_tone_profile=proposed, source_document_ids=[d.id for d in documents])


@router.get("/{client_id}/prospects", response_model=list[ProspectOut])
def list_prospects(client_id: int, db: Session = Depends(get_db)):
    if not db.get(Client, client_id):
        raise HTTPException(404, "client not found")
    return db.query(Prospect).filter(Prospect.client_id == client_id).all()


@router.post("/{client_id}/prospects/discover")
def discover_prospects(client_id: int, db: Session = Depends(get_db)):
    """Stub — finding reputed prospects requires LinkedIn people/content search,
    which is the same category of action that has repeatedly triggered account-wide
    checkpoints (see scraper/feed_search.py, deliberately not wired into any job).
    This intentionally does not call any scraper code. Real implementation lands
    once that checkpoint problem is solved, likely adapting feed_search.py."""
    if not db.get(Client, client_id):
        raise HTTPException(404, "client not found")
    return {"status": "not_yet_available", "prospects": []}


@router.post("/{client_id}/prospects/{prospect_id}/approve", response_model=WatchCreatorOut)
def approve_prospect(client_id: int, prospect_id: int, db: Session = Depends(get_db)):
    prospect = db.get(Prospect, prospect_id)
    if not prospect or prospect.client_id != client_id:
        raise HTTPException(404, "prospect not found")

    creator = WatchCreator(client_id=client_id, profile_url=prospect.profile_url, label=prospect.name)
    db.add(creator)
    prospect.status = ProspectStatus.approved
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "this profile is already tracked for this client")
    db.refresh(creator)
    return creator


@router.post("/{client_id}/prospects/{prospect_id}/reject")
def reject_prospect(client_id: int, prospect_id: int, db: Session = Depends(get_db)):
    prospect = db.get(Prospect, prospect_id)
    if not prospect or prospect.client_id != client_id:
        raise HTTPException(404, "prospect not found")
    prospect.status = ProspectStatus.rejected
    db.commit()
    return {"ok": True}


@router.post("/{client_id}/sync")
def sync_client(client_id: int, db: Session = Depends(get_db)):
    """Manually trigger discovery for this client right now. Runs synchronously —
    deliberately paced (rate-limited delays between each watch-creator), so this
    can take a few minutes for clients with several creators. That pacing is a
    safety feature, not a bug."""
    client = db.get(Client, client_id)
    if not client:
        raise HTTPException(404, "client not found")

    try:
        new_posts = run_discovery_for_client(db, client)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"sync failed: {e}")

    return {"new_posts": new_posts}
