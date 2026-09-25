"""WhatsApp history import: uploaded export → parsed messages → the shared ingest path.

The whole file is one transaction: every message is staged with `ingest.stage_message` and
the `imports` row is added before a single commit, so a failed import leaves nothing
behind and can simply be retried. Imported links are saved as `pending`; the worker
enriches them later at the slower import pace.
"""

import io
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import PurePosixPath
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Import, SourceChannel
from app.services import ingest
from app.services.whatsapp_parser import DateOrder, parse_chat

# A text-only export of years of chat is a few MB; these limits only stop accidents
# (a media export, a zip bomb) from filling memory.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_CHAT_BYTES = 50 * 1024 * 1024
SAMPLE_ERRORS = 10
# iOS names the chat file inside its zip `_chat.txt`.
_IOS_CHAT_FILENAME = "_chat.txt"
# A zip starts with a local file header, or an end-of-archive record if it's empty.
_ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06")


class ImportFileError(ValueError):
    """The upload isn't a WhatsApp chat export we can read."""


class ImportTooLargeError(ValueError):
    """The upload, or the chat inside the zip, is over the size limit."""


@dataclass
class ImportStats:
    messages: int = 0
    links_found: int = 0
    created: int = 0
    duplicates: int = 0
    unparseable_lines: int = 0
    sample_errors: list[str] = field(default_factory=list)


def _chat_file_from_zip(data: bytes) -> bytes:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        chats = [
            info
            for info in archive.infolist()
            if not info.is_dir()
            and info.filename.lower().endswith(".txt")
            # macOS adds resource-fork copies of every file under __MACOSX/.
            and not info.filename.startswith("__MACOSX/")
        ]
        if len(chats) > 1:
            chats = [c for c in chats if PurePosixPath(c.filename).name == _IOS_CHAT_FILENAME]
        if len(chats) != 1:
            raise ImportFileError("The zip should contain exactly one chat .txt file")
        chat = chats[0]
        if chat.file_size > MAX_CHAT_BYTES:
            raise ImportTooLargeError("The chat file in the zip is too large")
        with archive.open(chat) as file:
            # Read at most one byte past the limit, in case the zip lies about the size.
            content = file.read(MAX_CHAT_BYTES + 1)
    if len(content) > MAX_CHAT_BYTES:
        raise ImportTooLargeError("The chat file in the zip is too large")
    return content


def read_chat_text(data: bytes) -> str:
    """Return the chat text from an uploaded `.txt` export, or a `.zip` holding one."""
    try:
        if data.startswith(_ZIP_SIGNATURES):
            data = _chat_file_from_zip(data)
    except zipfile.BadZipFile as exc:
        raise ImportFileError(f"Could not read the zip: {exc}") from exc
    if b"\x00" in data:
        raise ImportFileError("The file is not a text file")
    # utf-8-sig drops the byte-order mark WhatsApp puts at the start of some exports.
    return data.decode("utf-8-sig", errors="replace")


async def import_whatsapp(
    session: AsyncSession,
    *,
    filename: str,
    data: bytes,
    date_order: DateOrder,
    tz: ZoneInfo,
) -> tuple[Import, ImportStats]:
    """Import a WhatsApp export. Commits once, at the end.

    Raises `ImportFileError`, `ImportTooLargeError` or `DateOrderError` before writing
    anything if the file can't be imported.
    """
    parsed = parse_chat(read_chat_text(data), date_order=date_order, tz=tz)
    if not parsed.messages:
        raise ImportFileError(
            "No WhatsApp messages found. Upload the .txt or .zip from Export chat."
        )

    stats = ImportStats(
        messages=len(parsed.messages),
        unparseable_lines=parsed.unparseable_lines,
        sample_errors=parsed.errors[:SAMPLE_ERRORS],
    )
    for message in parsed.messages:
        try:
            outcome = await ingest.stage_message(
                session,
                text=message.text,
                source_channel=SourceChannel.WHATSAPP_IMPORT,
                sender=message.sender,
                shared_at=message.sent_at,
            )
        except ingest.NoUrlsFoundError:
            continue
        stats.created += len(outcome.created)
        stats.duplicates += len(outcome.duplicates)
    stats.links_found = stats.created + stats.duplicates

    record = Import(source="whatsapp", filename=filename, stats=asdict(stats))
    session.add(record)
    await session.commit()
    return record, stats


async def list_imports(session: AsyncSession) -> list[Import]:
    """Every past import, newest first."""
    return list((await session.scalars(select(Import).order_by(Import.created_at.desc()))).all())
