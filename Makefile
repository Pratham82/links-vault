# Shortcuts for the long docker compose commands. Run `make` to list them.
#
#   Server (Hetzner):  make deploy, make logs, make backup, ...
#   Mac (dashboard):   make dashboard, make dashboard-logs, ...
#   Development:       make dev, make test, make lint
#
# Pass services with s=, e.g. `make logs s=bot` or `make restart s="api worker"`.

SERVER    := docker compose -f docker-compose.server.yml
DASHBOARD := docker compose -f docker-compose.dashboard.yml
DEV       := docker compose

API_URL    ?= https://links-api.hetzner.pratham82.in
BACKUP_DIR ?= $(HOME)/backups
s ?=

.DEFAULT_GOAL := help
.PHONY: help up deploy ps logs restart stop down backup restore psql health \
	dashboard dashboard-logs dashboard-stop dashboard-down dev dev-stop dev-down test lint format

help: ## List the commands
	@grep -hE '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-16s %s\n", $$1, $$2}'

# ---------------------------------------------------------------- server (Hetzner)

up: ## Server: start the backend (db, api, worker, bot) / apply .env changes
	$(SERVER) up -d

deploy: ## Server: pull, rebuild and restart the backend (no web)
	git pull --ff-only
	$(SERVER) up -d --build

ps: ## Server: what's running
	$(SERVER) ps

logs: ## Server: follow logs (s=bot for one service; Ctrl+C to exit)
	$(SERVER) logs -f --tail 100 $(s)

restart: ## Server: restart services (s=bot, or all)
	$(SERVER) restart $(s)

stop: ## Server: stop everything (keeps data)
	$(SERVER) stop

down: ## Server: stop and remove the containers (keeps data volumes)
	$(SERVER) down

backup: ## Server: dump the database to ~/backups (BACKUP_DIR=... to override)
	@mkdir -p $(BACKUP_DIR)
	$(SERVER) exec -T db pg_dump -U linkvault -Fc linkvault > $(BACKUP_DIR)/linkvault-$$(date +%F).dump
	@ls -lh $(BACKUP_DIR)/linkvault-$$(date +%F).dump

restore: ## Server: restore a dump, replacing current data (FILE=path/to.dump)
	@test -n "$(FILE)" || { echo "Usage: make restore FILE=path/to.dump"; exit 1; }
	$(SERVER) exec -T db pg_restore -U linkvault -d linkvault --clean --if-exists --no-owner < $(FILE)

psql: ## Server: open a psql shell on the database
	$(SERVER) exec db psql -U linkvault -d linkvault

health: ## Check the hosted API (API_URL=... to override)
	@curl -sS $(API_URL)/health && echo

# ---------------------------------------------------------------- Mac (dashboard)

dashboard: ## Mac: build and start the dashboard on http://localhost:3000
	$(DASHBOARD) up -d --build

dashboard-logs: ## Mac: follow the dashboard's logs
	$(DASHBOARD) logs -f --tail 100

dashboard-stop: ## Mac: stop the dashboard
	$(DASHBOARD) stop

dashboard-down: ## Mac: stop and remove the dashboard container
	$(DASHBOARD) down

# ---------------------------------------------------------------- development

dev: ## Dev: run the full stack locally (docker-compose.yml)
	$(DEV) up -d --build

dev-stop: ## Dev: stop the local stack (keeps data)
	$(DEV) stop

dev-down: ## Dev: stop and remove the local containers (keeps data volumes)
	$(DEV) down

test: ## Dev: backend tests (needs Postgres, e.g. `docker compose up -d db`)
	cd backend && uv run pytest

lint: ## Dev: ruff check + format check on the backend
	cd backend && uv run ruff check . && uv run ruff format --check .

format: ## Dev: format the backend with ruff
	cd backend && uv run ruff format .
