import uuid
from datetime import datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.models import ContentType, LinkStatus, SourceChannel


class LinkIngest(BaseModel):
    """Body of `POST /links`: one message that may contain several URLs."""

    text: str = Field(min_length=1, max_length=10_000)
    source_channel: SourceChannel
    sender: str = Field(min_length=1, max_length=200)
    # Must include a UTC offset so we never have to guess the timezone.
    shared_at: AwareDatetime | None = None


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


class Health(BaseModel):
    status: str
    database: str
