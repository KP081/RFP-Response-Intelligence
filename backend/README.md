# Backend

FastAPI service for RFP Response Intelligence. Dependencies and developer tooling
are managed with `uv` from this directory.

Run the service with `uv run uvicorn app.main:app --reload`. It reads local
configuration from `backend/.env` (or environment variables); start from
`infra/.env.example` and provide `DATABASE_URL` for a real health check.

## Session / Authentication Model (Task 06 / F18)

This service uses **stateless JWT** authentication:

- **Access tokens**: 15-minute lifetime, delivered as httpOnly cookies, validated via `Authorization: Bearer` header or cookie
- **Refresh tokens**: 30-day lifetime, delivered as httpOnly cookies, validated via cookie only
- **Logout**: Client-side cookie clearing only (best-effort; no server-side revocation list)
- **Validation**: `app.modules.auth.dependencies.get_current_user` handles both header and cookie validation (per F6)

This choice is documented here per Task 06's explicit requirement to "resolve early whether sessions are stateless JWT or server-side... Document whichever choice is made and why."

Cross-reference: `app/modules/auth/dependencies.py`, `app/modules/auth/service.py`, `app/core/audit.py` (for RLS context setting).

## Resetting Keycloak after editing realm-export.json

Keycloak only imports `infra/keycloak/realm-export.json` when its realm doesn't already exist in
its database. After the first `docker compose up`, further edits to that file will silently not
take effect until you run:

    make reset-keycloak

This drops and recreates only Keycloak's own database and forces a clean reimport — it does not
affect application data. A full `docker compose down -v` also works but wipes everything,
including your seeded orgs/users/documents.
