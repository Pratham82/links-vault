from fastapi import FastAPI

from app.api import health, imports, links, thumbnails


def create_app() -> FastAPI:
    app = FastAPI(title="Link Vault", version="0.1.0")
    app.include_router(health.router)
    app.include_router(links.router)
    app.include_router(imports.router)
    app.include_router(thumbnails.router)
    return app


app = create_app()
