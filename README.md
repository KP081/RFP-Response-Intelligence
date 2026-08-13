# RFP Response Intelligence

RFP Response Intelligence is a multi-tenant workspace for ingesting request-for-proposal documents, extracting structured requirements, matching them to organizational knowledge, and producing auditable proposal drafts.

## Repository layout

```text
repo-root/
├── backend/             # Python service, migrations, and backend tests
│   ├── app/             # Application packages (introduced by later tasks)
│   ├── alembic/         # Database migrations
│   └── tests/           # Mirrors the app/ package structure
├── frontend/            # React/Vite client and frontend tests
│   ├── src/             # Pages, components, API client, and shared utilities
│   └── tests/
├── infra/               # Local infrastructure configuration and Terraform
├── .github/workflows/   # CI workflows
└── plan/                # Sequenced implementation plan
```

Python 3.12 dependencies are managed with [uv](https://docs.astral.sh/uv/); `backend/pyproject.toml` is the backend dependency and tool configuration source of truth. The frontend uses Node 20 and pnpm.

See [plan/00-INDEX.md](plan/00-INDEX.md) to continue implementation.
