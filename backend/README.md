# Backend

FastAPI service for RFP Response Intelligence. Dependencies and developer tooling
are managed with `uv` from this directory.

Run the service with `uv run uvicorn app.main:app --reload`. It reads local
configuration from `backend/.env` (or environment variables); start from
`infra/.env.example` and provide `DATABASE_URL` for a real health check.
