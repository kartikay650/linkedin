import enum

from sqlalchemy import (
    Column, Integer, String, Text, Boolean, ForeignKey, DateTime, Enum, JSON, Float, UniqueConstraint
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db import Base


class BurnerStatus(str, enum.Enum):
    active = "active"
    needs_relogin = "needs_relogin"
    dead = "dead"


class DraftStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    posted = "posted"


class DocumentSource(str, enum.Enum):
    youtube = "youtube"
    upload = "upload"


class DocumentStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    done = "done"
    failed = "failed"


class ProspectSource(str, enum.Enum):
    keyword_search = "keyword_search"  # only source today; discovery itself is stubbed


class ProspectStatus(str, enum.Enum):
    pending_review = "pending_review"
    approved = "approved"
    rejected = "rejected"


class Client(Base):
    __tablename__ = "clients"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    specialty = Column(String, nullable=False)
    linkedin_url = Column(String, nullable=True)  # the client's own profile, not a watch-creator
    tone_profile = Column(Text, default="")  # short doc: voice, do's/don'ts, sample phrases
    topics = Column(JSON, default=list)  # keywords/hashtags to search
    burner_id = Column(Integer, ForeignKey("burners.id"), nullable=True)

    # Structured brand profile, synthesised from the client's strategy doc(s) and
    # human-reviewed. Feeds the relevance scorer and the reply drafter. All free
    # text so a person can edit each section directly (human-in-the-loop).
    voice_guide = Column(Text, default="")        # how they write: tone, style, do's/don'ts
    viewpoints = Column(Text, default="")          # their actual opinions/stances on topics
    audience = Column(Text, default="")            # who they're reaching + that audience's pain points
    key_messages = Column(Text, default="")        # core positioning statements / proof points
    cta_rules = Column(Text, default="")           # how/when to point to resources; what NOT to push
    guardrails = Column(Text, default="")          # hard rules the drafter must never violate
    created_at = Column(DateTime, server_default=func.now())

    burner = relationship("Burner", back_populates="clients")
    watch_creators = relationship("WatchCreator", back_populates="client", cascade="all, delete-orphan")
    posts = relationship("Post", back_populates="client", cascade="all, delete-orphan")
    documents = relationship("ClientDocument", back_populates="client", cascade="all, delete-orphan")
    prospects = relationship("Prospect", back_populates="client", cascade="all, delete-orphan")


class WatchCreator(Base):
    __tablename__ = "watch_creators"
    __table_args__ = (UniqueConstraint("client_id", "profile_url", name="uq_watch_creator_client_profile"),)

    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    profile_url = Column(String, nullable=False)
    label = Column(String, default="")

    client = relationship("Client", back_populates="watch_creators")


class ClientDocument(Base):
    __tablename__ = "client_documents"

    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    source_type = Column(Enum(DocumentSource), nullable=False)
    source_url = Column(String, nullable=True)  # youtube URL
    original_filename = Column(String, nullable=True)  # upload
    storage_path = Column(String, nullable=True)  # server-generated disk path, upload only
    extracted_text = Column(Text, default="")
    status = Column(Enum(DocumentStatus), default=DocumentStatus.pending)
    error_detail = Column(Text, default="")
    created_at = Column(DateTime, server_default=func.now())

    client = relationship("Client", back_populates="documents")


class Prospect(Base):
    __tablename__ = "prospects"

    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    profile_url = Column(String, nullable=False)
    name = Column(String, default="")
    headline = Column(String, default="")
    source = Column(Enum(ProspectSource), default=ProspectSource.keyword_search)
    status = Column(Enum(ProspectStatus), default=ProspectStatus.pending_review)
    discovered_at = Column(DateTime, server_default=func.now())

    client = relationship("Client", back_populates="prospects")


class Burner(Base):
    __tablename__ = "burners"

    id = Column(Integer, primary_key=True)
    label = Column(String, nullable=False)
    status = Column(Enum(BurnerStatus), default=BurnerStatus.active)
    storage_state_path = Column(String, nullable=False)  # path to persisted cookies/session
    # Optional explicit per-burner proxy override. Normally left NULL — the proxy
    # is derived from settings.proxy_url_template + proxy_session_id (see scraper/proxy.py).
    proxy_url = Column(String, nullable=True)  # e.g. http://user:pass@proxy.packetstream.io:31112
    # Stable sticky-session id → this burner always gets the SAME residential exit IP.
    proxy_session_id = Column(String, nullable=True)
    # Fingerprint knobs pinned per burner; should track the proxy's country.
    locale = Column(String, nullable=True)  # e.g. "en-US"; NULL → default
    timezone_id = Column(String, nullable=True)  # e.g. "America/New_York"; NULL → default
    last_health_check_at = Column(DateTime, nullable=True)
    last_health_ok = Column(Boolean, default=True)
    actions_today = Column(Integer, default=0)
    actions_reset_at = Column(DateTime, nullable=True)

    clients = relationship("Client", back_populates="burner")


class Post(Base):
    __tablename__ = "posts"

    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    burner_id = Column(Integer, ForeignKey("burners.id"), nullable=True)

    source_type = Column(String, nullable=False)  # "keyword" | "creator"
    source_ref = Column(String, nullable=False)  # keyword text or creator profile url

    author_name = Column(String, default="")
    author_profile_url = Column(String, default="")
    post_url = Column(String, nullable=False, unique=True)
    content_snippet = Column(Text, default="")
    posted_at = Column(DateTime, nullable=True)
    engagement = Column(JSON, default=dict)  # {"likes": n, "comments": n}

    relevance_score = Column(Float, nullable=True)
    relevance_reason = Column(Text, default="")

    fetched_at = Column(DateTime, server_default=func.now())

    client = relationship("Client", back_populates="posts")
    drafts = relationship("Draft", back_populates="post", cascade="all, delete-orphan")


class Draft(Base):
    __tablename__ = "drafts"

    id = Column(Integer, primary_key=True)
    post_id = Column(Integer, ForeignKey("posts.id"), nullable=False)
    variant_index = Column(Integer, default=0)
    text = Column(Text, nullable=False)
    edited_text = Column(Text, nullable=True)
    status = Column(Enum(DraftStatus), default=DraftStatus.pending)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    post = relationship("Post", back_populates="drafts")


class BurnerEvent(Base):
    __tablename__ = "burner_events"

    id = Column(Integer, primary_key=True)
    burner_id = Column(Integer, ForeignKey("burners.id"), nullable=False)
    event_type = Column(String, nullable=False)  # "health_check" | "checkpoint" | "banned" | "redistributed"
    detail = Column(Text, default="")
    created_at = Column(DateTime, server_default=func.now())
