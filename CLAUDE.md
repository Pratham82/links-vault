# CLAUDE.md — Link Vault

Read `README.md` first. It is the spec: data model, API, pipeline, phases, and acceptance criteria. If the spec and this file disagree, ask rather than guess.

## About the owner

I'm a senior frontend engineer (React/Next.js) growing into backend work. This project is partly a learning exercise, so:

- Prefer clear, idiomatic code over clever code.
- In PR descriptions, briefly explain any backend pattern I might not know (e.g. why `SKIP LOCKED`, how the session lifecycle works).
- Don't introduce new libraries or services without explaining why in the PR.

## Working rules

- **One phase per session / PR.** Only implement the phase you were asked for. Don't start the next one.
- **Stay in scope.** Don't refactor or reformat unrelated files.
- **Tests are required.** Every endpoint, service, and parser change ships with tests. A phase is not done until `uv run pytest` and `uv run ruff check` pass.
- **No real network in tests.** Mock all outbound HTTP with `respx`. Never call X, Instagram, Telegram, or an LLM from tests.
- **No secrets in code.** Everything comes from environment variables via `app/config.py`. Keep `.env.example` updated when adding config.
- **Migrations.** Every schema change gets an Alembic migration. Never edit a migration that's already merged.
- If something in the spec is ambiguous, pick the simplest reasonable option, note it under "Assumptions" in the PR description, and move on.

## Repo layout

```
link-vault/
├── README.md
├── CLAUDE.md
├── docker-compose.yml
├── .env.example
├── backend/
│   ├── pyproject.toml
│   ├── alembic/
│   ├── app/
│   │   ├── main.py            # FastAPI app factory, routers
│   │   ├── config.py          # pydantic-settings
│   │   ├── db.py              # async engine + session dependency
│   │   ├── models.py          # SQLAlchemy models
│   │   ├── schemas.py         # Pydantic request/response models
│   │   ├── auth.py            # X-API-Key dependency
│   │   ├── api/
│   │   │   ├── links.py
│   │   │   ├── imports.py
│   │   │   └── digest.py
│   │   ├── services/
│   │   │   ├── ingest.py      # extract → normalize → dedupe → save (shared by all adapters)
│   │   │   ├── normalize.py
│   │   │   ├── preview.py
│   │   │   ├── classify.py    # content_type rules
│   │   │   ├── tagger.py      # Phase 5, pluggable
│   │   │   ├── whatsapp_parser.py
│   │   │   └── digest.py
│   │   ├── worker.py          # enrichment loop
│   │   └── bot/
│   │       └── telegram.py    # long-polling bot, calls the API over HTTP
│   └── tests/
│       ├── conftest.py
│       ├── fixtures/          # sample WhatsApp exports, sample HTML pages
│       └── ...
└── web/                       # Next.js dashboard (Phase 4)
```

## Commands

```bash
# backend
cd backend
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "message"

# full stack
docker compose up --build

# web (Phase 4+)
cd web && npm install && npm run dev && npm run lint
```

## Backend conventions

- Python 3.12, full type hints, `ruff` for lint + format.
- **Async everywhere:** async SQLAlchemy 2.0 (`AsyncSession`, `select()` style, no legacy `Query`), `httpx.AsyncClient` for outbound calls.
- One `AsyncSession` per request via a FastAPI dependency. Services receive the session as an argument; they don't create their own.
- Pydantic v2 schemas separate from ORM models. Never return ORM objects directly from endpoints.
- Business logic lives in `services/`. Routers stay thin: validate, call a service, return a schema.
- **All adapters go through `services/ingest.py`.** Telegram, the WhatsApp import, and `POST /links` must share the same extract/normalize/dedupe code path.
- Timestamps are timezone-aware UTC in the DB. Convert to `Asia/Kolkata` only for display and digest dates.
- Outbound fetches: set a realistic User-Agent, timeouts (connect 5s / read 10s), bounded concurrency from config, and per-domain delay for imports.
- Errors: 4xx for client problems with a clear `detail`; never leak stack traces.

## Domain rules (don't get these wrong)

- **Dedupe key** for live captures is `normalized_url`. A duplicate share increments `share_count` and appends the note; it does not create a row.
- **Imports** dedupe on `(normalized_url, shared_at)`. Re-importing the same file must create zero new rows.
- **`shared_at` vs `created_at`:** digests and dashboard ordering use `shared_at`. Imported links keep their original message time.
- **Status:** 404/410/DNS failure → `dead` (don't retry). Timeouts/5xx → `failed` (retry with backoff, max 3). Success → `enriched`.
- **Previews never block ingestion.** `POST /links` returns immediately with `status = pending`; the worker enriches later.
- **WhatsApp dates:** day/month order comes from the `date_order` parameter (default `DMY`). Never infer it silently.
- **Telegram:** ignore messages from user IDs not in `TELEGRAM_ALLOWED_USER_IDS`. Log them, but don't reply.

## Frontend conventions (Phase 4+)

- Next.js App Router, TypeScript strict, Tailwind.
- Server components by default; client components only for interactivity (filters, editing).
- Talk to the API through one typed client module; the API key stays server-side (route handlers / server actions), never in the browser bundle.
- Link cards show: thumbnail, title, site, type badge, tags, note, shared date. Handle missing images gracefully.

## Testing notes

- Tests use a real Postgres from `DATABASE_URL` (transactions rolled back per test). If Postgres isn't available in the environment, install and start it in the setup script rather than switching to SQLite — we use Postgres-only features (arrays, enums, `SKIP LOCKED`).
- Sample WhatsApp exports live in `tests/fixtures/whatsapp/` — both Android and iOS formats, multi-line messages, system lines, and `\u202f` before AM/PM. Add a fixture for every parser bug you fix.
- Sample HTML pages for OG parsing live in `tests/fixtures/html/`.

## Definition of done (per phase)

1. Acceptance criteria from the README phase table are met.
2. Tests added and passing; ruff clean.
3. Migrations included if the schema changed.
4. `.env.example` and README updated if config or API changed.
5. PR description includes: what changed, how to run it, assumptions made, and a short "concepts used" note for anything backend-specific.
