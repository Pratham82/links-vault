# Link Vault

A personal inbox for every link I share — from multiple phones, desktop, and my old WhatsApp group — with rich previews, automatic classification, and (later) daily Markdown notes for Obsidian.

Single user. Self-hosted: the backend runs on a Hetzner server, the dashboard on a Mac Mini M4. Not a public product.

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

```mermaid
flowchart TD
  tg["Telegram bot<br/>live capture"] --> api
  ext["Bookmarklet / extension<br/>later"] -.-> api
  wa["WhatsApp export upload<br/>history backfill"] --> api
  api["FastAPI<br/>POST /links, POST /import/whatsapp"] --> db[("Postgres")]
  db <--> worker["worker<br/>normalize, dedupe, preview, classify"]
  db --> dash["Next.js dashboard<br/>browse, filter, search"]
  db -.-> obs["Daily .md export to Obsidian<br/>later"]
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

### Where it runs

```mermaid
flowchart LR
  phone["Phone / desktop"] -- share --> tg["Telegram"]
  subgraph hetzner["Hetzner server, always on"]
    nginx["NGINX<br/>TLS, links-api.hetzner.pratham82.in"]
    cron["cron 21:45 UTC<br/>make backup"]
    subgraph compose["docker-compose.server.yml"]
      bot["bot<br/>long polling"]
      api["api (FastAPI)<br/>checks X-API-Key"]
      worker["worker<br/>enriches pending links"]
      db[("Postgres 16<br/>no published port")]
    end
  end
  subgraph mac["Mac Mini, browse only"]
    browser["Browser"] -- "localhost:3000" --> web["web (Next.js)<br/>docker-compose.dashboard.yml"]
  end
  bot -- "long-polls, outbound only" --> tg
  bot -- "POST /links" --> api
  web -- "HTTPS + X-API-Key" --> nginx
  nginx -- "127.0.0.1:8200" --> api
  api -- SQL --> db
  worker -- "claims pending, SKIP LOCKED" --> db
  worker -- "fetch previews" --> sites["Linked sites"]
  cron -.-> db
```

`db`, `api`, `worker` and `bot` run on a Hetzner server (`docker-compose.server.yml`), so capture keeps working when the Mac sleeps. Only the API is reachable from outside, over HTTPS at `https://links-api.hetzner.pratham82.in`, behind the host's NGINX and the `X-API-Key` header. The dashboard runs on the Mac (`docker-compose.dashboard.yml`) and calls that URL from its server side, so the key never reaches the browser.

Tailscale is no longer part of the setup. It's only useful if you want to open the Mac's dashboard from another device, and then only while the Mac is awake. See [Deployment](#deployment) for the setup.

---

## Tech stack

- **Backend:** Python 3.12, FastAPI, async SQLAlchemy 2.0, Pydantic v2, Alembic, httpx
- **Bot:** python-telegram-bot (async, long polling)
- **Worker:** Postgres-backed job loop (`SELECT … FOR UPDATE SKIP LOCKED` on `status = 'pending'`) — no Redis
- **Frontend:** Next.js (App Router), TypeScript, Tailwind, shadcn/ui (Base UI), Motion
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
| `image_url`      | text, nullable | Cached thumbnail path (`/thumbnails/{file}`) or remote URL if caching failed          |
| `site_name`      | text, nullable |                                                                                       |
| `content_type`   | enum           | `tweet`, `instagram`, `youtube`, `github_repo`, `article`, `product`, `docs`, `other` |
| `tags`           | text[]         | Topic tags (Phase 5)                                                                  |
| `status`         | enum           | `pending`, `enriched`, `failed`, `dead`                                               |
| `share_count`    | int            | Incremented on duplicate shares                                                       |
| `enrich_attempts`| int            | Worker bookkeeping: enrichment tries so far (max 3)                                   |
| `next_attempt_at`| timestamptz    | Worker bookkeeping: lease while being enriched, then retry backoff after a failure    |
| `shared_at`      | timestamptz    | When I originally shared it (import uses message time)                                |
| `created_at`     | timestamptz    | When stored                                                                           |
| `updated_at`     | timestamptz    |                                                                                       |

Unique constraint: `(normalized_url)` for live captures (a partial unique index over rows whose `source_channel` isn't `whatsapp_import`). Imports dedupe on `(normalized_url, shared_at)` so re-imports are idempotent.

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
| `POST`   | `/import/whatsapp`  | Upload `.txt` or `.zip` export (multipart field `file`; `date_order`, `timezone` query params); returns an import report |
| `GET`    | `/imports`          | List past imports with stats                                                                                         |
| `GET`    | `/digest/{date}.md` | Markdown digest for a date (by `shared_at`)                                                                          |
| `GET`    | `/thumbnails/{file}`| A cached preview image, as referenced by a link's `image_url`                                                        |
| `GET`    | `/health`           | Health check (no auth). `200 {"status":"ok","database":"ok"}`, or `503` if Postgres is unreachable                    |

`GET /links` query params: `type`, `tag`, `source`, `from` / `to` (ISO 8601 with offset; `from` inclusive, `to` exclusive, by `shared_at`), `q` (case-insensitive substring of url/title/description/note), `limit` (1–200, default 50), `offset`. Results are newest `shared_at` first and wrapped as `{ items, total, limit, offset }`.

`POST /links` returns `201 { created: [...], duplicates: [...] }`, or `422` if the text contains no `http(s)` URL. `shared_at`, when given, must include a UTC offset. A URL whose normalized form is already saved lands in `duplicates`: its `share_count` goes up and the message's note is appended on a new line; `url`, `source_channel` and `shared_at` keep the first share's values.

`PATCH /links/{id}` takes any of `{ note, tags, content_type }` and changes only those: `note: null` or `""` clears the note, `tags` replaces the whole list (lowercased, `#` and repeats dropped, at most 20 tags of 50 characters), and unknown fields are rejected with `422`. `DELETE /links/{id}` returns `204` and also removes the link's cached thumbnail.

---

## Ingestion pipeline

1. **Extract** — find every URL in the message text; the remaining text becomes `note`.
2. **Normalize** — lowercase host, strip fragments and tracking params (`utm_*`, `fbclid`, `gclid`, `igsh`, `igshid`, `si`, `s`, `ref`…), resolve known short links (`t.co`, `bit.ly`, `youtu.be` → canonical). `youtu.be` and host aliases (`twitter.com` → `x.com`) are rewritten at ingest; short links that need an HTTP request (`t.co`, `bit.ly`, `amzn.to`…) are resolved by the worker, which merges the row into an existing link if the target is already saved.
3. **Dedupe** — if `normalized_url` exists, increment `share_count` and append the note; don't create a new row.
4. **Queue** — save with `status = pending`.
5. **Preview (worker)** — fetch Open Graph / Twitter Card tags; use oEmbed for X, YouTube, Instagram where available; fall back to URL + note. Timeouts and bounded concurrency. Unreachable (404/410/DNS) → `dead`; other errors → `failed` with retry (after 1 min, then 5 min; 3 attempts in total). The preview image is downloaded and served from `/thumbnails/{file}`, because X/Instagram CDN URLs expire.
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

**Using it:**

```bash
curl -X POST 'localhost:8000/import/whatsapp?date_order=DMY' -H 'X-API-Key: change-me' \
  -F 'file=@WhatsApp Chat with Links.zip'
# {"id": "…", "filename": "WhatsApp Chat with Links.zip", "messages": 1840, "links_found": 912,
#  "created": 912, "duplicates": 0, "unparseable_lines": 1, "sample_errors": ["line 1: …"]}
curl localhost:8000/imports -H 'X-API-Key: change-me'   # past imports, newest first
```

- Query params: `date_order` (`DMY` default, `MDY`, or `YMD`) and `timezone` (IANA name, default `Asia/Kolkata`). The export's times have no timezone, so they're read as local times in `timezone`.
- If a date in the file is impossible in `date_order` but valid in another order (e.g. `09/24/2026` with `DMY`), the upload is rejected with `422` naming the line and the order to use. Nothing is saved.
- The whole file is imported in one transaction: an upload either imports completely or not at all, and can be retried.
- `messages` counts messages from people, not system lines or media placeholders. `links_found` = `created` + `duplicates`. `sample_errors` shows up to 10 unparseable lines.
- Uploads are limited to 25 MB (a text-only export is far smaller). In a `.zip`, the chat must be the only `.txt` file, or be named `_chat.txt`.
- The worker enriches imported links in the background, at most `IMPORT_PREVIEW_CONCURRENCY` at once and `IMPORT_DOMAIN_DELAY_SECONDS` apart per site. Live links have their own quota, so new shares still get previews during a big backfill.

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
DOCS_ENABLED=true                    # false on the public server (no /docs, /openapi.json)
API_BASE_URL=http://localhost:8000   # bot → API outside Docker; compose sets http://api:8000
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_USER_IDS=123456789,987654321
PREVIEW_CONCURRENCY=5
WORKER_POLL_SECONDS=5
THUMBNAIL_DIR=data/thumbnails  # compose sets /data/thumbnails (shared volume)
IMPORT_PREVIEW_CONCURRENCY=2
IMPORT_DOMAIN_DELAY_SECONDS=5
POSTGRES_PASSWORD=                   # server only, see Deployment
API_HOST_PORT=8200                   # server only: loopback port NGINX proxies to
DASHBOARD_API_BASE_URL=https://links-api.hetzner.pratham82.in  # Mac only
TAGGER=none            # none | ollama | api
OLLAMA_URL=http://host.docker.internal:11434
OBSIDIAN_VAULT_PATH=
```

## Local development

```bash
cp .env.example .env
docker compose up --build
# API:  http://localhost:8000/docs
# Web:  http://localhost:3000
```

The `api` container runs `alembic upgrade head` on startup. Quick smoke test:

```bash
curl -X POST localhost:8000/links -H 'X-API-Key: change-me' -H 'content-type: application/json' \
  -d '{"text": "check this https://github.com/astral-sh/uv", "source_channel": "api", "sender": "curl"}'
curl localhost:8000/links -H 'X-API-Key: change-me'
```

### Telegram bot

1. Create a bot with [@BotFather](https://t.me/BotFather) (`/newbot`) and put the token in `.env` as `TELEGRAM_BOT_TOKEN`.
2. Find your numeric Telegram user ID: send the bot any message and check `docker compose logs bot` for `Ignoring update from unauthorized Telegram user id=…` (or ask [@userinfobot](https://t.me/userinfobot)). Add it to `TELEGRAM_ALLOWED_USER_IDS` (comma-separated for several accounts) and restart: `docker compose up -d bot`.
3. Share a link to the bot from any app. It replies `Saved 1 link: …`, and the link shows up in `GET /links` with `source_channel = telegram`.

The bot uses long polling, so it needs no public URL. Messages from users not on the allowlist are logged and never answered. Text and captions are both read, and URLs behind linked words are included. To run the bot outside Docker (with the API on localhost:8000): `cd backend && uv run python -m app.bot.telegram`.

### Enrichment worker

The `worker` container picks up `pending` links, fetches their previews (oEmbed for YouTube and X, Open Graph tags for everything else), sets `content_type`, caches the thumbnail, and marks each link `enriched`, `failed` or `dead`. It needs no setup: `docker compose up` starts it, and `docker compose logs worker` shows what it did. A link posted with `POST /links` usually shows its title within a few seconds.

Thumbnails live in the `thumbnails` volume and are served at `GET /thumbnails/{file}` (needs `X-API-Key`, like every other endpoint). To run the worker outside Docker: `cd backend && uv run python -m app.worker`.

### Dashboard

`docker compose up` also starts the dashboard at http://localhost:3000 (`web` service). It shows every link as a card (thumbnail, title, site, type, tags, note, shared date), newest `shared_at` first, 48 per page. Filter by type, source, tag and date range (calendar days in India time, both inclusive), or search title, URL, description and note. Clicking a type badge or a `#tag` filters by it. Each card can be edited (note, tags, type) or deleted.

The dashboard calls the API from its server, never from the browser, so `API_KEY` stays off the page. It needs no extra config: it reuses `API_KEY` from `.env`. To run it outside Docker, with the API on localhost:8000:

```bash
cd web
npm install
printf 'API_KEY=change-me\nAPI_BASE_URL=http://localhost:8000\n' > .env.local
npm run dev
```

Tags are stored lowercase, without `#`; a link can have up to 20 tags of up to 50 characters.

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

## Deployment

The backend runs on the Hetzner server so the Telegram bot and worker keep going while the Mac sleeps. The dashboard stays on the Mac and calls the hosted API.

| Where       | Compose file                   | Services                     | Reachable at                                            |
| ----------- | ------------------------------ | ---------------------------- | ------------------------------------------------------- |
| Hetzner     | `docker-compose.server.yml`    | `db`, `api`, `worker`, `bot` | `https://links-api.hetzner.pratham82.in` (via NGINX)    |
| Mac Mini    | `docker-compose.dashboard.yml` | `web`                        | http://localhost:3000                                   |
| Development | `docker-compose.yml`           | everything                   | localhost                                               |

On the server only the API is published, and only on `127.0.0.1:${API_HOST_PORT:-8200}`, so the host's NGINX is the one way in from the internet. The database has no published port. The bot uses long polling, so it needs no inbound port either. `DOCS_ENABLED=false` hides `/docs` and `/openapi.json`; every other route except `/health` needs `X-API-Key`.

### 1. Server: start the backend

```bash
mkdir -p ~/projects && cd ~/projects
git clone https://github.com/Pratham82/links-vault.git && cd links-vault
cp .env.example .env
# Edit .env:
#   API_KEY=<openssl rand -hex 32>
#   POSTGRES_PASSWORD=<openssl rand -hex 24>
#   DATABASE_URL=postgresql+asyncpg://linkvault:<same password>@db:5432/linkvault
#   TELEGRAM_BOT_TOKEN / TELEGRAM_ALLOWED_USER_IDS as on the Mac
docker compose -f docker-compose.server.yml up -d --build db   # just the database for now
```

The password inside `DATABASE_URL` must be exactly `POSTGRES_PASSWORD`. Postgres only reads `POSTGRES_PASSWORD` when it first creates the `pgdata` volume, so changing it later doesn't change the database. If the API logs `InvalidPasswordError: password authentication failed for user "linkvault"`, make the two `.env` values match, then set the database to that password (keeps your data):

```bash
docker compose -f docker-compose.server.yml exec db \
  psql -U linkvault -d linkvault -c "ALTER USER linkvault PASSWORD '<POSTGRES_PASSWORD>'"
docker compose -f docker-compose.server.yml up -d
```

If you are migrating existing data (step 3), leave the other services stopped until it is restored. Otherwise start everything: `docker compose -f docker-compose.server.yml up -d --build`, then `curl localhost:8200/health`.

### 2. Server: NGINX and HTTPS

1. Add a DNS `A` record for `links-api.hetzner.pratham82.in` pointing at the server.
2. Paste both `server` blocks from `deploy/nginx/links-vault.conf` into the `http {}` block of `/etc/nginx/nginx.conf`, then add the new name to the existing certificate:
   ```bash
   sudo nginx -t && sudo systemctl reload nginx
   sudo certbot certonly --nginx --expand -d hetzner.pratham82.in -d api.hetzner.pratham82.in \
     -d links-api.hetzner.pratham82.in
   sudo systemctl reload nginx
   ```
   The 443 block reuses the `hetzner.pratham82.in` certificate files, which already exist, so `nginx -t` passes straight away; the new name only shows a certificate warning until certbot has expanded the certificate. `certonly` renews the certificate without rewriting `nginx.conf`, so the live file stays the same as your reference copy.
3. Check: `curl https://links-api.hetzner.pratham82.in/health` returns `{"status":"ok",...}` once the API is up, `/docs` is 404 and `/links` without a key is 401.

The block raises `client_max_body_size` to 26 MB so WhatsApp exports (up to 25 MB) aren't rejected by NGINX. If you change `API_HOST_PORT`, change its `proxy_pass` too.

### 3. Move existing data from the Mac

Stop capture on the Mac first. Two bots long-polling the same token make Telegram reject one of them (409 Conflict), and anything saved after the dump would be lost.

On the Mac, in the repo:

```bash
docker compose stop bot worker api
docker compose exec -T db pg_dump -U linkvault -Fc linkvault > linkvault.dump
docker compose run --rm --no-deps -T worker tar czf - -C /data/thumbnails . > thumbnails.tgz
scp linkvault.dump thumbnails.tgz <server>:projects/links-vault/
```

On the server, in `~/projects/links-vault` (with only `db` running, from step 1):

```bash
docker compose -f docker-compose.server.yml exec -T db \
  pg_restore -U linkvault -d linkvault --clean --if-exists --no-owner < linkvault.dump
docker compose -f docker-compose.server.yml run --rm --no-deps -T worker \
  tar xzf - -C /data/thumbnails < thumbnails.tgz
docker compose -f docker-compose.server.yml up -d --build
docker compose -f docker-compose.server.yml logs -f api bot   # migrations are already at head
```

`-Fc` writes Postgres's compressed "custom" format, which `pg_restore` reads; `--clean --if-exists` drops anything already there first and `--no-owner` ignores the Mac's role names.

### 4. Mac: dashboard only

```bash
docker compose down             # stop the full local stack (frees port 3000; volumes are kept as a fallback)
# .env on the Mac: API_KEY=<the server's key>, DASHBOARD_API_BASE_URL=https://links-api.hetzner.pratham82.in
make dashboard                  # = docker compose -f docker-compose.dashboard.yml up -d --build
```

The dashboard is at http://localhost:3000. Without Docker, put the same `API_KEY` and `API_BASE_URL=https://links-api.hetzner.pratham82.in` in `web/.env.local` and run `npm run dev`. Send the bot a link while the Mac is asleep; it appears in the dashboard once the Mac wakes.

### Make commands

The `Makefile` at the repo root wraps the long compose commands. Run them inside the repo folder; `make` on its own lists them all. Pass services with `s=`, e.g. `make logs s=bot`. If `make` is missing, install it with `sudo apt install make` on the server or `xcode-select --install` on the Mac.

Every service has `restart: unless-stopped`, so containers come back by themselves after a crash or a reboot (as long as Docker starts at boot: `sudo systemctl enable docker` on the server). You only run something when a thing changes.

**Server** (Hetzner, `~/projects/links-vault`)

| Command                                                 | When                                                        |
| ------------------------------------------------------- | ----------------------------------------------------------- |
| `make deploy`                                           | New code merged: rebuilds the backend, runs migrations      |
| `make up`                                               | Start the backend (db, api, worker, bot); also after `.env` |
| `make ps`                                               | See what's running                                          |
| `make logs`                                             | Follow all logs (Ctrl+C to exit)                            |
| `make logs s=bot`                                       | Follow one service (`api`, `worker`, `bot`, `db`)           |
| `make restart s=bot`                                    | Restart one service (leave out `s=` to restart all)         |
| `make stop`                                             | Pause everything (`make up` resumes it)                     |
| `make down`                                             | Stop and remove the containers (data is kept)               |
| `make backup`                                           | Back up the database to `~/backups` now                     |
| `make restore FILE=~/backups/linkvault-2026-09-26.dump` | Replace the database with a backup                          |
| `make psql`                                             | Open an SQL shell (`\q` to exit)                            |
| `make health`                                           | Check the API is up                                         |

The server's compose file has no `web` service, so these commands only ever touch the backend; the dashboard runs on the Mac.

**Mac Mini** (dashboard)

| Command               | When                                                   |
| --------------------- | ------------------------------------------------------ |
| `make dashboard`      | Build and start the dashboard at http://localhost:3000 |
| `make dashboard-logs` | Follow the dashboard's logs                            |
| `make dashboard-stop` | Pause it                                               |
| `make dashboard-down` | Stop and remove it                                     |
| `make health`         | Check the hosted API from the Mac                      |

After pulling new code on the Mac, run `git pull && make dashboard`. Plain `docker compose down` doesn't stop the dashboard: it runs as its own compose project, so use `make dashboard-down`.

**Development** (either machine)

| Command         | When                                                   |
| --------------- | ------------------------------------------------------ |
| `make dev`      | Start the full stack locally (`docker-compose.yml`)    |
| `make dev-stop` | Pause it                                               |
| `make dev-down` | Stop and remove its containers (data is kept)          |
| `make test`     | Backend tests (needs Postgres: `docker compose up -d db`) |
| `make lint`     | Ruff check and format check                            |
| `make format`   | Format the backend with ruff                           |

Never run `docker compose … down -v`: `-v` deletes the database and thumbnail volumes, and there's deliberately no make command for it.

Is it up? From anywhere:

```bash
curl https://links-api.hetzner.pratham82.in/health                               # {"status":"ok","database":"ok"}
curl -s -o /dev/null -w '%{http_code}\n' https://links-api.hetzner.pratham82.in/docs    # 404 (docs off)
curl -s -o /dev/null -w '%{http_code}\n' https://links-api.hetzner.pratham82.in/links   # 401 (no key)
curl -s -H "X-API-Key: $API_KEY" 'https://links-api.hetzner.pratham82.in/links?limit=1'  # newest link
```

On the server itself, `curl localhost:8200/health` skips NGINX, which tells you whether a failure is the API or the proxy.

### Updating and backups

On the server, `make deploy` ships the latest code. On the Mac, `git pull && make dashboard` rebuilds the dashboard.

The data now lives only on the server, so back it up nightly with `crontab -e`. Cron uses the server's clock, which is UTC, so `45 21 * * *` is 03:15 in India:

```
45 21 * * * cd ~/projects/links-vault && make backup
```

Copy those dumps off the server now and then (or enable Hetzner backups).

## Screenshots

<img width="1481" height="1325" alt="image" src="https://github.com/user-attachments/assets/05b39c9a-17f7-4b90-8fe9-0bc7e94cc5a4" />

