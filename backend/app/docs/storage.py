"""Where uploaded client documents live. Dual-mode:

- Supabase Storage when supabase_url is configured (required on Vercel — its disk
  is ephemeral, so local writes wouldn't survive between requests).
- Local disk (client_docs_dir) otherwise, for local/Docker dev.

Text extraction always happens from a temp file (see routers/clients.upload_document),
so this module only handles *persisting/removing* the original file. The stored
identifier is either a real filesystem path or a "supabase://bucket/key" URI.
"""
import os
import uuid

import httpx

from app.config import settings

_SUPA_PREFIX = "supabase://"


def _use_supabase() -> bool:
    return bool(settings.supabase_url and settings.supabase_service_key)


def store_document(client_id: int, filename: str, content: bytes) -> str:
    """Persist the file and return a storage identifier."""
    key = f"{client_id}/{uuid.uuid4().hex}_{filename}"
    if _use_supabase():
        bucket = settings.supabase_docs_bucket
        url = f"{settings.supabase_url.rstrip('/')}/storage/v1/object/{bucket}/{key}"
        r = httpx.post(
            url,
            headers={
                "Authorization": f"Bearer {settings.supabase_service_key}",
                "Content-Type": "application/octet-stream",
                "x-upsert": "true",
            },
            content=content,
            timeout=60,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"Supabase Storage upload failed ({r.status_code}): {r.text[:200]}")
        return f"{_SUPA_PREFIX}{bucket}/{key}"

    # local disk
    client_dir = os.path.join(settings.client_docs_dir, str(client_id))
    os.makedirs(client_dir, exist_ok=True)
    path = os.path.join(client_dir, os.path.basename(key))
    with open(path, "wb") as f:
        f.write(content)
    return path


def delete_document(storage_path: str) -> None:
    if not storage_path:
        return
    if storage_path.startswith(_SUPA_PREFIX):
        bucket_key = storage_path[len(_SUPA_PREFIX):]
        bucket, _, key = bucket_key.partition("/")
        url = f"{settings.supabase_url.rstrip('/')}/storage/v1/object/{bucket}/{key}"
        try:
            httpx.request("DELETE", url, headers={"Authorization": f"Bearer {settings.supabase_service_key}"}, timeout=30)
        except Exception:
            pass  # best-effort; a leftover object is harmless
    elif os.path.exists(storage_path):
        os.remove(storage_path)
