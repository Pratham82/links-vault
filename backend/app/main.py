from fastapi import FastAPI

from app.api import health, imports, links, thumbnails
from app.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    # With DOCS_ENABLED=false (the public server), the docs and schema routes don't exist.
    docs = (
        {} if settings.docs_enabled else {"docs_url": None, "redoc_url": None, "openapi_url": None}
    )
    app = FastAPI(title="Link Vault", version="0.1.0", **docs)
    app.include_router(health.router)
    app.include_router(links.router)
    app.include_router(imports.router)
    app.include_router(thumbnails.router)
    return app


app = create_app()
