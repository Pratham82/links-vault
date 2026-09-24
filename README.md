# Link Vault

A personal inbox for every link I share — from multiple phones, desktop, and my old WhatsApp group — with rich previews, automatic classification, and (later) daily Markdown notes for Obsidian.

Single user. Self-hosted on a Mac Mini M4. Not a public product.

---

## Problem

Today I dump links from X, Instagram, YouTube, GitHub, articles, etc. into a WhatsApp group from different devices. It works as a dumping ground but:

- Nothing is classified or searchable.
- Previews are inconsistent and disappear over time.
- There's no way to review "what did I save today" or move it into Obsidian.

## Goals

1. **Capture** a link from any device in one or two taps.
2. **Enrich** every link with a stable preview (title, description, image, site).
3. **Classify** each link by type (tweet, reel, repo, article…) and topic tags.
4. **Import** my existing WhatsApp group history with original dates.
5. **Browse** everything in a dashboard with filters and search.
6. **Export** a daily Markdown digest into my Obsidian vault (secondary).

## Non-goals (for now)

- Multi-user accounts, sharing, or public hosting.
- Live WhatsApp integration (official API needs an Official Business Account; unofficial libraries risk a ban). Revisit later as an optional adapter.
- Full-page archiving / reading mode.
- Mobile native apps. Capture goes through Telegram's share sheet.

---

## Architecture

```
Phones / Desktop
   │  share → Telegram bot          (live capture)
   │  bookmarklet / extension       (desktop, later)
   │  WhatsApp export upload        (history backfill)
   ▼
FastAPI  ── POST /links, POST /import/whatsapp ──► Postgres
   │
   └─ worker: normalize → dedupe → preview → classify
   ▼
Next.js dashboard (browse, filter, search)
   ▼
Daily .md export → Obsidian vault
```

**Principle:** the API is channel-agnostic. Every input (Telegram, desktop, import, future WhatsApp) is an adapter that calls the same ingestion service.

### Services (docker-compose)

| Service  | Purpose                                                                       |
| -------- | ----------------------------------------------------------------------------- |
| `db`     | Postgres                                                                      |
| `api`    | FastAPI app (REST API + ingestion service)                                    |
| `worker` | Background enrichment: picks up `pending` links, fetches previews, classifies |
| `bot`    | Telegram bot using **long polling** (no public URL needed); calls the API     |
| `web`    | Next.js dashboard                                                             |

Remote access from other devices is via Tailscale — nothing is exposed to the public internet.

---

## Tech stack

- **Backend:** Python 3.12, FastAPI, async SQLAlchemy 2.0, Pydantic v2, Alembic, httpx
- **Bot:** python-telegram-bot (async, long polling)
- **Worker:** Postgres-backed job loop (`SELECT … FOR UPDATE SKIP LOCKED` on `status = 'pending'`) — no Redis
- **Frontend:** Next.js (App Router), TypeScript, Tailwind
- **Tooling:** uv, ruff, pytest, pytest-asyncio, respx (HTTP mocking), Docker Compose
- **LLM tagging (Phase 5):** pluggable — local Ollama model or a hosted API

---

## Data model

### `links`

| Column           | Type           | Notes                                                                                 |
| ---------------- | -------------- | ------------------------------------------------------------------------------------- |
| `id`             | UUID           | PK                                                                                    |
| `url`            | text           | As received                                                                           |
| `normalized_url` | text           | Tracking params stripped, short links resolved; indexed                               |
| `source_channel` | enum           | `telegram`, `desktop`, `whatsapp_import`, `api`                                       |
| `sender`         | text           | Telegram user / WhatsApp sender name / device label                                   |
| `note`           | text, nullable | Any text sent alongside the URL                                                       |
| `title`          | text, nullable | From OG / oEmbed                                                                      |
| `description`    | text, nullable |                                                                                       |
| `image_url`      | text, nullable | Cached thumbnail path or remote URL                                                   |
| `site_name`      | text, nullable |                                                                                       |
| `content_type`   | enum           | `tweet`, `instagram`, `youtube`, `github_repo`, `article`, `product`, `docs`, `other` |
| `tags`           | text[]         | Topic tags (Phase 5)                                                                  |
| `status`         | enum           | `pending`, `enriched`, `failed`, `dead`                                               |
| `share_count`    | int            | Incremented on duplicate shares                                                       |
| `shared_at`      | timestamptz    | When I originally shared it (import uses message time)                                |
| `created_at`     | timestamptz    | When stored                                                                           |
| `updated_at`     | timestamptz    |                                                                                       |

Unique constraint: `(normalized_url)` for live captures. Imports dedupe on `(normalized_url, shared_at)` so re-imports are idempotent.

### `imports`

| Column       | Type        | Notes                                          |
| ------------ | ----------- | ---------------------------------------------- |
| `id`         | UUID        | PK                                             |
| `source`     | text        | `whatsapp`                                     |
| `filename`   | text        |                                                |
| `stats`      | jsonb       | messages, links, duplicates, unparseable lines |
| `created_at` | timestamptz |                                                |

---

## API

All endpoints except `/health` require header `X-API-Key` (single-user auth); a missing or wrong key returns `401`.

| Method   | Path                | Description                                                                                                          |
| -------- | ------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `POST`   | `/links`            | Ingest a message: `{ text, source_channel, sender, shared_at? }`. Extracts all URLs, returns created/duplicate links |
| `GET`    | `/links`            | List with filters: `type`, `tag`, `source`, `from`, `to`, `q`, pagination                                            |
| `GET`    | `/links/{id}`       | Single link                                                                                                          |
| `PATCH`  | `/links/{id}`       | Edit note / tags / type                                                                                              |
| `DELETE` | `/links/{id}`       | Delete                                                                                                               |
| `POST`   | `/import/whatsapp`  | Upload `.txt` or `.zip` export; returns an import report                                                             |
| `GET`    | `/imports`          | List past imports with stats                                                                                         |
| `GET`    | `/digest/{date}.md` | Markdown digest for a date (by `shared_at`)                                                                          |
| `GET`    | `/health`           | Health check (no auth). `200 {"status":"ok","database":"ok"}`, or `503` if Postgres is unreachable                    |

`GET /links` query params: `type`, `tag`, `source`, `from` / `to` (ISO 8601 with offset; `from` inclusive, `to` exclusive, by `shared_at`), `q` (case-insensitive substring of url/title/description/note), `limit` (1–200, default 50), `offset`. Results are newest `shared_at` first and wrapped as `{ items, total, limit, offset }`.

`POST /links` returns `201 { created: [...], duplicates: [...] }`, or `422` if the text contains no `http(s)` URL. `shared_at`, when given, must include a UTC offset.

---

## Ingestion pipeline

1. **Extract** — find every URL in the message text; the remaining text becomes `note`.
2. **Normalize** — lowercase host, strip fragments and tracking params (`utm_*`, `fbclid`, `gclid`, `igsh`, `igshid`, `si`, `s`, `ref`…), resolve known short links (`t.co`, `bit.ly`, `youtu.be` → canonical).
3. **Dedupe** — if `normalized_url` exists, increment `share_count` and append the note; don't create a new row.
4. **Queue** — save with `status = pending`.
5. **Preview (worker)** — fetch Open Graph / Twitter Card tags; use oEmbed for X, YouTube, Instagram where available; fall back to URL + note. Timeouts and bounded concurrency. Unreachable (404/410/DNS) → `dead`; other errors → `failed` with retry.
6. **Type classification (worker)** — deterministic domain rules (see below).
7. **Topic tags (worker, Phase 5)** — LLM call with title + description + note → up to 5 tags from a controlled-but-growable vocabulary.

### Content type rules

| Domain / pattern                                                    | Type          |
| ------------------------------------------------------------------- | ------------- |
| `x.com`, `twitter.com` `/status/`                                   | `tweet`       |
| `instagram.com` `/p/`, `/reel/`                                     | `instagram`   |
| `youtube.com/watch`, `youtu.be`, `/shorts/`                         | `youtube`     |
| `github.com/{owner}/{repo}`                                         | `github_repo` |
| Known docs hosts (`*.readthedocs.io`, `docs.*`, `developer.*`, MDN) | `docs`        |
| `amazon.*`, `flipkart.com` etc.                                     | `product`     |
| Has `og:type = article`                                             | `article`     |
| Else                                                                | `other`       |

---

## WhatsApp import

**Getting the file:** in the WhatsApp group → ⋮ → More → Export chat → **Without media**. Upload the resulting `.txt` or `.zip`.

**Parser requirements:**

- Support Android format: `24/09/2026, 10:15 pm - Name: message`
- Support iOS format: `[24/09/26, 10:15:32 PM] Name: message`
- Handle 12h/24h time, 2- and 4-digit years, and optional narrow no-break spaces (`\u202f`) before AM/PM.
- A line not starting with a timestamp is a continuation of the previous message.
- Skip system lines (encryption notice, joins/leaves, "<Media omitted>", deleted messages).
- Day/month order is ambiguous — accept a `date_order` param (`DMY` default for India) and never guess silently.

**Behaviour:**

- Each extracted URL goes through the normal pipeline with `source_channel = whatsapp_import`, `shared_at = message time`, `sender = message author`.
- Idempotent: re-uploading overlapping exports must not create duplicates.
- Enrichment of imported links is throttled (low concurrency, per-domain delay) so X/Instagram don't rate-limit.
- Response is an import report: `{ messages, links_found, created, duplicates, unparseable_lines, sample_errors[] }`.

---

## Daily digest (Obsidian)

`GET /digest/2026-09-24.md` returns:

```markdown
---
date: 2026-09-24
links: 7
---

# Links — 2026-09-24

## GitHub repos

- [owner/repo — Short description](https://github.com/owner/repo) #ai #tools

## Articles

- [Title](https://example.com/post) — _my note_ #react

## Tweets

- [@author: first line of tweet…](https://x.com/…)
```

Grouped by `content_type`, ordered by `shared_at`. A nightly job (n8n or cron) writes the file into the vault. A one-off backfill command can generate notes for past dates.

---

## Phases

| #   | Phase            | Scope                                                                                          | Acceptance criteria                                                                |
| --- | ---------------- | ---------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| 0   | Skeleton         | Compose, FastAPI, Postgres, Alembic, `POST/GET /links`, `/health`, API key auth, tests, CI     | `docker compose up` works; curl a link in and read it back; tests pass in CI       |
| 1   | Telegram capture | Bot (long polling), allowlist of my Telegram user IDs, calls `POST /links`, confirmation reply | Sharing from phone lands in DB; unknown users are ignored                          |
| 2   | Enrichment       | Normalization, dedupe, worker, OG/oEmbed preview, type rules, thumbnail caching                | Links get title/image/type; duplicates bump `share_count`; network mocked in tests |
| 3   | WhatsApp import  | Parser, `POST /import/whatsapp`, `imports` table, throttled backfill, report                   | Fixture exports (Android + iOS) parse correctly; re-import creates 0 new rows      |
| 4   | Dashboard        | Next.js card grid, filters (type, tag, source, date), search, edit note/tags                   | I prefer it over the WhatsApp group                                                |
| 5   | AI tags          | Pluggable tagger (Ollama / API), tags in bot reply + dashboard                                 | Tags are useful without manual fixing most of the time                             |
| 6   | Daily digest     | `/digest/{date}.md`, nightly writer, backfill command                                          | Daily note appears in Obsidian automatically                                       |
| 7   | Extras           | Desktop bookmarklet/extension, optional WhatsApp live adapter                                  | —                                                                                  |

---

## Configuration

See `.env.example`:

```
DATABASE_URL=postgresql+asyncpg://linkvault:linkvault@db:5432/linkvault
API_KEY=change-me
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_USER_IDS=123456789,987654321
PREVIEW_CONCURRENCY=5
IMPORT_PREVIEW_CONCURRENCY=2
TAGGER=none            # none | ollama | api
OLLAMA_URL=http://host.docker.internal:11434
OBSIDIAN_VAULT_PATH=
```

## Local development

```bash
cp .env.example .env
docker compose up --build
# API:  http://localhost:8000/docs
# Web:  http://localhost:3000   (Phase 4)
```

The `api` container runs `alembic upgrade head` on startup. Quick smoke test:

```bash
curl -X POST localhost:8000/links -H 'X-API-Key: change-me' -H 'content-type: application/json' \
  -d '{"text": "check this https://github.com/astral-sh/uv", "source_channel": "api", "sender": "curl"}'
curl localhost:8000/links -H 'X-API-Key: change-me'
```

Backend tests:

```bash
docker compose up -d db   # Postgres on localhost:5432, with a `linkvault_test` database
cd backend
uv sync
uv run pytest
```

Tests need a real Postgres at `DATABASE_URL` (default `postgresql+asyncpg://linkvault:linkvault@localhost:5432/linkvault_test`). The suite rebuilds the schema from the Alembic migrations once per run and rolls back each test's changes. If the database is unreachable, pytest stops with one message saying so.

- `linkvault_test` is created by `docker/postgres-init/` only when the `pgdata` volume is first created. For an older volume, run `docker compose down -v` once (this deletes local data) or `docker compose exec db createdb -U linkvault linkvault_test`.
- If port 5432 is taken (e.g. a Homebrew Postgres), set `POSTGRES_PORT=5433` in `.env` and point `DATABASE_URL` at that port.
