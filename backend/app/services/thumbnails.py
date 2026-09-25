"""Download preview images to local disk.

Image URLs from X and Instagram CDNs are signed and expire within days, so the worker keeps
its own copy and stores `/thumbnails/<file>` (served by `api/thumbnails.py`) as `image_url`.
A failed download is never fatal: the link keeps the remote image URL instead.
"""

import asyncio
import logging
import re
import uuid
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

URL_PREFIX = "/thumbnails/"
MAX_THUMBNAIL_BYTES = 5_000_000
_EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}
# Only names we generate ourselves, so a request can never reach outside the directory.
FILENAME_RE = re.compile(r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}\.(jpg|png|webp|gif)")


def _write_atomically(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write then rename, so the API never serves a half-written file.
    tmp = path.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.replace(path)


async def cache_thumbnail(
    client: httpx.AsyncClient, image_url: str, directory: Path, link_id: uuid.UUID
) -> str | None:
    """Save the image as `<directory>/<link_id>.<ext>`; return its URL path, or None."""
    try:
        async with client.stream("GET", image_url, follow_redirects=True) as response:
            if response.status_code != 200:
                logger.info("Thumbnail %s returned %s", image_url, response.status_code)
                return None
            content_type = response.headers.get("content-type", "").split(";")[0].strip()
            extension = _EXTENSIONS.get(content_type.lower())
            if extension is None:
                logger.info("Thumbnail %s has unsupported type %r", image_url, content_type)
                return None
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data += chunk
                if len(data) > MAX_THUMBNAIL_BYTES:
                    logger.info("Thumbnail %s is larger than %d bytes", image_url, len(data))
                    return None
    except httpx.HTTPError as exc:
        logger.info("Thumbnail %s could not be fetched: %r", image_url, exc)
        return None

    filename = f"{link_id}.{extension}"
    try:
        # File I/O blocks, so run it in a thread instead of stalling the event loop.
        await asyncio.to_thread(_write_atomically, directory / filename, bytes(data))
    except OSError as exc:
        logger.warning("Could not save thumbnail to %s: %r", directory, exc)
        return None
    return URL_PREFIX + filename
