import os
import tempfile

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.docs.extract import extract_text
from app.docs.storage import store_document, delete_document as delete_stored_document
from app.docs.youtube import TranscriptUnavailable, extract_youtube_transcript
from app.jobs.discovery import run_discovery_for_client, start_discovery_for_client
from app.llm.brand_profile import extract_brand_profile
from app.llm.tone_synthesis import synthesize_tone_profile
from app.scraper.linkedin_lookup import resolve_creator_url, resolve_creators
from app.models import Client, ClientDocument, DocumentStatus, DocumentSource, Prospect, ProspectStatus, WatchCreator
from app.schemas import (
    BrandProfileOut, ClientCreate, ClientDocumentOut, ClientOut, ClientUpdate, ExtractBrandRequest,
    ProspectOut, ResolveCreatorRequest, ToneSynthesisOut, TrackCreatorsRequest, WatchCreatorCreate,
    WatchCreatorOut, YoutubeDocumentCreate,
)

router = APIRouter(prefix="/clients", tags=["clients"])

ALLOWED_UPLOAD_EXTENSIONS = {".pdf", ".docx", ".txt"}


@router.get("", response_model=list[ClientOut])
def list_clients(db: Session = Depends(get_db)):
    return db.query(Client).all()


@router.post("", response_model=ClientOut)
def create_client(payload: ClientCreate, db: Session = Depends(get_db)):
    client = Client(**payload.model_dump())
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


@router.post("/doc-text")
def doc_text(file: UploadFile):
    """Extract plain text from ONE uploaded file and return it. Files are sent
    individually (not batched) so a large image-heavy PDF doesn't blow the
    serverless request-body limit. Nothing is persisted."""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(400, f"unsupported file type {ext!r} — allowed: {sorted(ALLOWED_UPLOAD_EXTENSIONS)}")
    contents = file.file.read()
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tf:
        tf.write(contents)
        tmp_path = tf.name
    try:
        text = extract_text(tmp_path)
    except Exception:
        text = ""
    finally:
        os.remove(tmp_path)
    return {"filename": file.filename, "text": text or ""}


@router.post("/extract-brand")
def extract_brand(payload: ExtractBrandRequest):
    """Extract a brand profile from already-extracted text (see /doc-text). The
    payload is small text, so no request-size concerns. Nothing is persisted."""
    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(400, "no text to extract from")
    profile = extract_brand_profile(Client(name="", specialty=""), [ClientDocument(extracted_text=text)])
    if not profile:
        raise HTTPException(502, "couldn't extract details from the documents")
    return profile


@router.post("/extract-from-upload")
def extract_from_upload(files: list[UploadFile], db: Session = Depends(get_db)):
    """Read one or more uploaded strategy docs and return extracted client details
    (name, specialty, topics, voice, viewpoints, audience, key messages, CTA rules,
    guardrails, suggested creators) WITHOUT creating anything. Powers the document-
    first add-client flow: upload → auto-fill the form → human reviews → Create."""
    texts = []
    for f in files or []:
        ext = os.path.splitext(f.filename or "")[1].lower()
        if ext not in ALLOWED_UPLOAD_EXTENSIONS:
            continue
        contents = f.file.read()
        if len(contents) > settings.max_upload_size_mb * 1024 * 1024:
            raise HTTPException(400, f"{f.filename} exceeds {settings.max_upload_size_mb}MB limit")
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tf:
            tf.write(contents)
            tmp_path = tf.name
        try:
            t = extract_text(tmp_path)
            if t and t.strip():
                texts.append(t)
        except Exception:
            pass
        finally:
            os.remove(tmp_path)

    if not texts:
        raise HTTPException(400, "couldn't read any text from those files (supported: .pdf, .docx, .txt)")

    stub_client = Client(name="", specialty="")
    stub_docs = [ClientDocument(extracted_text=t) for t in texts]
    profile = extract_brand_profile(stub_client, stub_docs)
    if not profile:
        raise HTTPException(502, "couldn't extract details from the documents")
    return profile


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

    # Extract text from a temp file (works on serverless, where /tmp is the only
    # writable path), then persist the original to Supabase Storage or local disk.
    extracted, status, error = "", DocumentStatus.done, ""
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tf:
        tf.write(contents)
        tmp_path = tf.name
    try:
        extracted = extract_text(tmp_path)
    except Exception as e:
        status, error = DocumentStatus.failed, str(e)
    finally:
        os.remove(tmp_path)

    storage_path = store_document(client_id, file.filename or "upload", contents)

    doc = ClientDocument(
        client_id=client_id,
        source_type=DocumentSource.upload,
        original_filename=file.filename,
        storage_path=storage_path,
        extracted_text=extracted,
        status=status,
        error_detail=error,
    )
    db.add(doc)
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
    delete_stored_document(doc.storage_path)
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


@router.post("/{client_id}/extract-brand-profile", response_model=BrandProfileOut)
def extract_brand_profile_route(client_id: int, db: Session = Depends(get_db)):
    """Extract a structured brand profile (voice, viewpoints, audience, key messages,
    CTA rules, guardrails, topics, suggested creators) from the client's processed
    documents. Never saves — the human reviews/edits each section and PATCHes the
    client to apply. Same human-review gate as tone synthesis and draft replies."""
    client = db.get(Client, client_id)
    if not client:
        raise HTTPException(404, "client not found")

    documents = db.query(ClientDocument).filter(
        ClientDocument.client_id == client_id, ClientDocument.status == DocumentStatus.done
    ).all()
    if not documents:
        raise HTTPException(400, "no successfully-processed documents to extract from")

    profile = extract_brand_profile(client, documents)
    if not profile:
        raise HTTPException(502, "couldn't extract a brand profile from the documents")

    # NOTE: creator LinkedIn URLs are resolved separately (POST .../resolve-creator),
    # one per request, so this LLM call and the search lookups never share a single
    # request and can't jointly blow the serverless time limit.
    return BrandProfileOut(**profile, source_document_ids=[d.id for d in documents])


@router.post("/{client_id}/track-suggested-creators")
def track_suggested_creators(client_id: int, payload: TrackCreatorsRequest, db: Session = Depends(get_db)):
    """Resolve the suggested creators' LinkedIn URLs (in parallel) and auto-track the
    ones we can verify as the right person. Unverified/ambiguous ones are returned as
    'skipped' for the human to add manually. Used at the end of onboarding."""
    client = db.get(Client, client_id)
    if not client:
        raise HTTPException(404, "client not found")

    items = [{"name": c.name, "profile_url": c.profile_url, "reason": c.reason} for c in payload.creators]
    resolved = resolve_creators(items, client.specialty or "")

    tracked, skipped = [], []
    for c in resolved:
        url = (c.get("profile_url") or "").strip()
        if c.get("verified") and url:
            db.add(WatchCreator(client_id=client_id, profile_url=url, label=c["name"]))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()  # already tracked for this client
            tracked.append(c["name"])
        else:
            skipped.append(c["name"])
    return {"tracked": tracked, "skipped": skipped}


@router.post("/{client_id}/resolve-creator")
def resolve_creator_route(client_id: int, payload: ResolveCreatorRequest, db: Session = Depends(get_db)):
    """Resolve ONE suggested creator's name to a LinkedIn URL (+verified flag).
    Split out from extraction so each request is a single fast Apify search run —
    the frontend calls this per creator, progressively."""
    client = db.get(Client, client_id)
    if not client:
        raise HTTPException(404, "client not found")
    url, verified = resolve_creator_url(payload.name, client.specialty or "")
    return {"name": payload.name, "profile_url": url, "verified": verified}


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
    """Trigger discovery for this client. In webhook mode (serverless) it fires the
    Apify runs and returns immediately — posts arrive shortly via /apify/webhook. In
    polling mode (local) it fetches synchronously and returns the new-post count."""
    client = db.get(Client, client_id)
    if not client:
        raise HTTPException(404, "client not found")

    try:
        if settings.apify_use_webhooks and settings.public_base_url:
            started = start_discovery_for_client(db, client)
            return {"status": "started", "runs": started}
        new_posts = run_discovery_for_client(db, client)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"sync failed: {e}")

    return {"new_posts": new_posts}
