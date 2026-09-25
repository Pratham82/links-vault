import uuid
from datetime import datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from app.models import ContentType, LinkStatus, SourceChannel


class LinkIngest(BaseModel):
    """Body of `POST /links`: one message that may contain several URLs."""

    text: str = Field(min_length=1, max_length=10_000)
    source_channel: SourceChannel
    sender: str = Field(min_length=1, max_length=200)
    # Must include a UTC offset so we never have to guess the timezone.
    shared_at: AwareDatetime | None = None


MAX_TAGS = 20
MAX_TAG_LENGTH = 50


class LinkUpdate(BaseModel):
    """Body of `PATCH /links/{id}`. Only the fields present are changed."""

    model_config = ConfigDict(extra="forbid")

    # null clears the note.
    note: str | None = Field(default=None, max_length=10_000)
    tags: list[str] | None = None
    content_type: ContentType | None = None

    @field_validator("note")
    @classmethod
    def _blank_note_is_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("tags")
    @classmethod
    def _clean_tags(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        # "#React ", "react" and "REACT" are one tag: "react". Order kept, repeats dropped.
        cleaned: list[str] = []
        for tag in value:
            tag = " ".join(tag.strip().lstrip("#").split()).lower()
            if len(tag) > MAX_TAG_LENGTH:
                raise ValueError(f"Tags can be at most {MAX_TAG_LENGTH} characters")
            if tag and tag not in cleaned:
                cleaned.append(tag)
        if len(cleaned) > MAX_TAGS:
            raise ValueError(f"A link can have at most {MAX_TAGS} tags")
        return cleaned


class LinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    url: str
    normalized_url: str
    source_channel: SourceChannel
    sender: str
    note: str | None
    title: str | None
    description: str | None
    image_url: str | None
    site_name: str | None
    content_type: ContentType
    tags: list[str]
    status: LinkStatus
    share_count: int
    shared_at: datetime
    created_at: datetime
    updated_at: datetime


class IngestResult(BaseModel):
    created: list[LinkOut]
    duplicates: list[LinkOut]


class LinkPage(BaseModel):
    items: list[LinkOut]
    total: int
    limit: int
    offset: int


class ImportReport(BaseModel):
    """Response of `POST /import/whatsapp`."""

    id: uuid.UUID
    filename: str
    messages: int
    links_found: int
    created: int
    duplicates: int
    unparseable_lines: int
    sample_errors: list[str]


class ImportStats(BaseModel):
    messages: int
    links_found: int
    created: int
    duplicates: int
    unparseable_lines: int
    sample_errors: list[str]


class ImportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source: str
    filename: str
    stats: ImportStats
    created_at: datetime


class Health(BaseModel):
    status: str
    database: str
