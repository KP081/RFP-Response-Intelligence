COMPOSE := docker compose --env-file infra/.env -f infra/docker-compose.yml

.PHONY: up down logs test lint

up:
	$(COMPOSE) up --build --detach --wait

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs --follow

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
