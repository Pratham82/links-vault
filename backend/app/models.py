import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SourceChannel(enum.StrEnum):
    TELEGRAM = "telegram"
    DESKTOP = "desktop"
    WHATSAPP_IMPORT = "whatsapp_import"
    API = "api"


class ContentType(enum.StrEnum):
    TWEET = "tweet"
    INSTAGRAM = "instagram"
    YOUTUBE = "youtube"
    GITHUB_REPO = "github_repo"
    ARTICLE = "article"
    PRODUCT = "product"
    DOCS = "docs"
    OTHER = "other"


class LinkStatus(enum.StrEnum):
    PENDING = "pending"
    ENRICHED = "enriched"
    FAILED = "failed"
    DEAD = "dead"


def _pg_enum(enum_cls: type[enum.Enum], name: str) -> Enum:
    # Store the lowercase values ("telegram"), not the Python member names ("TELEGRAM").
    return Enum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])


# Rows that live captures dedupe against. WhatsApp imports (Phase 3) dedupe on
# (normalized_url, shared_at) instead, so they're left out of the unique index.
LIVE_LINKS = text("source_channel <> 'whatsapp_import'")
# Rows the worker may still pick up.
ENRICH_QUEUE = text("status IN ('pending', 'failed')")


class Link(Base):
    __tablename__ = "links"
    __table_args__ = (
        Index("ix_links_shared_at", "shared_at"),
        Index(
            "uq_links_normalized_url_live",
            "normalized_url",
            unique=True,
            postgresql_where=LIVE_LINKS,
        ),
        Index("ix_links_enrich_queue", "next_attempt_at", postgresql_where=ENRICH_QUEUE),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    url: Mapped[str] = mapped_column(Text)
    normalized_url: Mapped[str] = mapped_column(Text, index=True)
    source_channel: Mapped[SourceChannel] = mapped_column(_pg_enum(SourceChannel, "source_channel"))
    sender: Mapped[str] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(Text)
    site_name: Mapped[str | None] = mapped_column(Text)
    content_type: Mapped[ContentType] = mapped_column(
        _pg_enum(ContentType, "content_type"),
        default=ContentType.OTHER,
        server_default=ContentType.OTHER.value,
    )
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(String), default=list, server_default=text("'{}'::varchar[]")
    )
    status: Mapped[LinkStatus] = mapped_column(
        _pg_enum(LinkStatus, "link_status"),
        default=LinkStatus.PENDING,
        server_default=LinkStatus.PENDING.value,
    )
    share_count: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    # Worker bookkeeping: how many times enrichment was tried, and when it may run next
    # (a lease while a worker holds the link, then the retry backoff after a failure).
    enrich_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    shared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
