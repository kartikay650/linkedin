from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ClientOut(BaseModel):
    id: int
    name: str
    specialty: str
    linkedin_url: Optional[str]
    tone_profile: str
    topics: list[str]
    burner_id: Optional[int]
    voice_guide: Optional[str] = None
    viewpoints: Optional[str] = None
    audience: Optional[str] = None
    key_messages: Optional[str] = None
    cta_rules: Optional[str] = None
    guardrails: Optional[str] = None

    class Config:
        from_attributes = True


class ClientCreate(BaseModel):
    name: str
    specialty: str
    linkedin_url: Optional[str] = None
    tone_profile: str = ""
    topics: list[str] = []
    burner_id: Optional[int] = None
    # Optional structured brand fields (set when created from an extracted doc).
    voice_guide: Optional[str] = None
    viewpoints: Optional[str] = None
    audience: Optional[str] = None
    key_messages: Optional[str] = None
    cta_rules: Optional[str] = None
    guardrails: Optional[str] = None


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    specialty: Optional[str] = None
    linkedin_url: Optional[str] = None
    tone_profile: Optional[str] = None
    topics: Optional[list[str]] = None
    burner_id: Optional[int] = None
    voice_guide: Optional[str] = None
    viewpoints: Optional[str] = None
    audience: Optional[str] = None
    key_messages: Optional[str] = None
    cta_rules: Optional[str] = None
    guardrails: Optional[str] = None


class ResolveCreatorRequest(BaseModel):
    name: str


class ExtractBrandRequest(BaseModel):
    text: str


class SuggestedCreator(BaseModel):
    name: str
    profile_url: str = ""   # auto-resolved from the name during onboarding; human confirms
    reason: str = ""
    verified: bool = False  # true if the resolved URL's search result matched the name


class BrandProfileOut(BaseModel):
    """Proposed brand profile extracted from a client's strategy doc(s). Never
    persisted directly — a human reviews/edits each section, then PATCHes the client."""
    voice_guide: str = ""
    viewpoints: str = ""
    audience: str = ""
    key_messages: str = ""
    cta_rules: str = ""
    guardrails: str = ""
    topics: list[str] = []
    suggested_creators: list[SuggestedCreator] = []
    source_document_ids: list[int] = []


class ProfilePreviewRequest(BaseModel):
    linkedin_url: str
    burner_id: int


class ProfilePreviewOut(BaseModel):
    name: str
    headline: str
    about: str


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


class ClientDocumentOut(BaseModel):
    id: int
    client_id: int
    source_type: str
    source_url: Optional[str]
    original_filename: Optional[str]
    status: str
    error_detail: str
    created_at: datetime

    class Config:
        from_attributes = True


class YoutubeDocumentCreate(BaseModel):
    url: str


class ToneSynthesisOut(BaseModel):
    proposed_tone_profile: str
    source_document_ids: list[int]


class ProspectOut(BaseModel):
    id: int
    client_id: int
    profile_url: str
    name: str
    headline: str
    source: str
    status: str
    discovered_at: datetime

    class Config:
        from_attributes = True
