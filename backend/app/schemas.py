from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ClientOut(BaseModel):
    id: int
    name: str
    specialty: str
    burner_id: Optional[int]

    class Config:
        from_attributes = True


class ClientCreate(BaseModel):
    name: str
    specialty: str
    tone_profile: str = ""
    topics: list[str] = []


class WatchCreatorOut(BaseModel):
    id: int
    client_id: int
    profile_url: str
    label: str

    class Config:
        from_attributes = True


class WatchCreatorCreate(BaseModel):
    profile_url: str
    label: str = ""


class BurnerOut(BaseModel):
    id: int
    label: str
    status: str
    last_health_check_at: Optional[datetime]
    last_health_ok: bool
    actions_today: int

    class Config:
        from_attributes = True


class PostOut(BaseModel):
    id: int
    client_id: int
    author_name: str
    author_profile_url: str
    post_url: str
    content_snippet: str
    posted_at: Optional[datetime]
    engagement: dict
    relevance_score: Optional[float]
    relevance_reason: str
    fetched_at: datetime

    class Config:
        from_attributes = True


class DraftOut(BaseModel):
    id: int
    post_id: int
    variant_index: int
    text: str
    edited_text: Optional[str]
    status: str

    class Config:
        from_attributes = True


class DraftUpdate(BaseModel):
    edited_text: Optional[str] = None
    status: Optional[str] = None  # "approved" | "rejected" | "posted"


class PostWithDrafts(PostOut):
    drafts: list[DraftOut] = []
