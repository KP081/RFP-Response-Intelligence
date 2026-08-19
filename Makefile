COMPOSE := docker compose --env-file infra/.env -f infra/docker-compose.yml

.PHONY: up down logs test lint seed reset-keycloak diagnose-keycloak

up:
	$(COMPOSE) up --build --detach --wait

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs --follow

seed:
	cd backend && uv sync --frozen --all-groups
	cd backend && uv run python -m scripts.seed_dev_data

test:
	cd backend && uv sync --frozen --all-groups
	cd backend && uv run pytest
	pnpm install --frozen-lockfile
	pnpm --dir frontend test

lint:
	cd backend && uv sync --frozen --all-groups
	cd backend && uv run ruff check .
	cd backend && uv run mypy app
	pnpm install --frozen-lockfile
	pnpm --dir frontend lint
	pnpm --dir frontend typecheck

reset-keycloak:
	$(COMPOSE) stop keycloak
	$(COMPOSE) exec -T postgres psql -U postgres -c "DROP DATABASE IF EXISTS keycloak;"
	$(COMPOSE) exec -T postgres psql -U postgres -c "CREATE DATABASE keycloak;"
	$(COMPOSE) up -d keycloak

diagnose-keycloak:
	@echo "--- KC_DB_URL (live container) ---"
	$(COMPOSE) exec keycloak env | grep KC_DB_URL
	@echo "--- Databases on postgres ---"
	$(COMPOSE) exec postgres psql -U postgres -l
	@echo "--- Realm count in keycloak db ---"
	$(COMPOSE) exec postgres psql -U postgres -d keycloak -c "SELECT count(*) FROM realm;" || echo "keycloak database or realm table missing"
	@echo "--- Users in keycloak db ---"
	$(COMPOSE) exec postgres psql -U postgres -d keycloak -c "SELECT username, realm_id FROM user_entity;" || true
