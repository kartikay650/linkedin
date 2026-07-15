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
    voice_guide: Optional[str] = None
    voice_samples: Optional[str] = None
    viewpoints: Optional[str] = None
    audience: Optional[str] = None
    key_messages: Optional[str] = None
    cta_rules: Optional[str] = None
    guardrails: Optional[str] = None
    personal_story: Optional[str] = None
    benchmark_examples: Optional[str] = None

    class Config:
        from_attributes = True


class ClientCreate(BaseModel):
    name: str
    specialty: str
    linkedin_url: Optional[str] = None
    tone_profile: str = ""
    topics: list[str] = []
    # Optional structured brand fields (set when created from an extracted doc).
    voice_guide: Optional[str] = None
    voice_samples: Optional[str] = None
    viewpoints: Optional[str] = None
    audience: Optional[str] = None
    key_messages: Optional[str] = None
    cta_rules: Optional[str] = None
    guardrails: Optional[str] = None
    personal_story: Optional[str] = None
    benchmark_examples: Optional[str] = None


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    specialty: Optional[str] = None
    linkedin_url: Optional[str] = None
    tone_profile: Optional[str] = None
    topics: Optional[list[str]] = None
    voice_guide: Optional[str] = None
    voice_samples: Optional[str] = None
    viewpoints: Optional[str] = None
    audience: Optional[str] = None
    key_messages: Optional[str] = None
    cta_rules: Optional[str] = None
    guardrails: Optional[str] = None
    personal_story: Optional[str] = None
    benchmark_examples: Optional[str] = None


class ResolveCreatorRequest(BaseModel):
    name: str


class ExtractBrandRequest(BaseModel):
    text: str


class SuggestedCreator(BaseModel):
    name: str
    profile_url: str = ""   # auto-resolved from the name during onboarding; human confirms
    reason: str = ""
    verified: bool = False  # true if the resolved URL's search result matched the name


class TrackCreatorsRequest(BaseModel):
    creators: list[SuggestedCreator] = []


class BrandProfileOut(BaseModel):
    """Proposed brand profile extracted from a client's strategy doc(s). Never
    persisted directly — a human reviews/edits each section, then PATCHes the client."""
    voice_guide: str = ""
    voice_samples: str = ""
    viewpoints: str = ""
    audience: str = ""
    key_messages: str = ""
    cta_rules: str = ""
    guardrails: str = ""
    personal_story: str = ""
    topics: list[str] = []
    suggested_creators: list[SuggestedCreator] = []
    source_document_ids: list[int] = []


class CreatorOut(BaseModel):
    id: int
    name: str
    profile_url: str
    headline: str
    kind: str
    active: bool
    client_ids: list[int] = []  # clients this creator is assigned to (fanned out only to these)

    class Config:
        from_attributes = True


class CreatorCreate(BaseModel):
    name: str = ""
    profile_url: str
    headline: str = ""
    kind: str = "creator"  # "creator" (track + comment) | "prospect" (lead-gen)


class CreatorUpdate(BaseModel):
    kind: Optional[str] = None
    active: Optional[bool] = None


class CreatorClientsUpdate(BaseModel):
    client_ids: list[int] = []


class ClientFeedbackOut(BaseModel):
    id: int
    client_id: int
    note: str
    created_at: datetime

    class Config:
        from_attributes = True


class ClientFeedbackCreate(BaseModel):
    note: str


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
    summary: str = ""
    fetched_at: datetime

    class Config:
        from_attributes = True


class DraftOut(BaseModel):
    id: int
    post_id: int
    variant_index: int
    text: str
    edited_text: Optional[str]
    provenance: list[dict] = []
    status: str

    class Config:
        from_attributes = True


class DraftUpdate(BaseModel):
    edited_text: Optional[str] = None
    status: Optional[str] = None  # "approved" | "rejected" | "posted"


class RefineDraftRequest(BaseModel):
    instruction: str


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
