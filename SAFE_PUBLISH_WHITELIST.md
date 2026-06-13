# Safe Publish Whitelist

This file lists the repository content that should remain in the public GitHub repository.

## Root Files

- `.gitignore`
- `.env.example`
- `README.md`
- `SAFE_PUBLISH_WHITELIST.md`
- `REMOVE_FROM_REPO.md`
- `docker-compose.yml`

## Backend

Keep:

- `backend/pyproject.toml`
- `backend/alembic.ini`
- `backend/Dockerfile`
- `backend/alembic/`
- `backend/src/`
- `backend/tests/`

Exclude from public repo:

- `backend/*.sqlite3`
- `backend/*.sqlite3-wal`
- `backend/*.sqlite3-shm`
- `backend/*.sqlite3.backup_*`
- `backend/logs/`
- `backend/ops/`
- `backend/.pytest_cache/`
- `backend/condocharge.egg-info/`

## Frontend

Keep:

- `frontend/package.json`
- `frontend/package-lock.json`
- `frontend/tsconfig.json`
- `frontend/tsconfig.node.json`
- `frontend/Dockerfile`
- `frontend/index.html`
- `frontend/vite.config.ts`
- `frontend/src/`

Exclude from public repo:

- `frontend/dist/`
- `frontend/node_modules/`
- `frontend/.vite/`
- `frontend/*.sqlite3`
- `frontend/tsconfig.tsbuildinfo`

## Documentation

Keep:

- `docs/ARCHITECTURE.md`
- `docs/BILLING_FLOW.md`
- `docs/DEPLOYMENT.md`
- `docs/PORTFOLIO_NOTES.md`
- `docs/RELEASE_CHECKLIST.md`
- `docs/SCREENSHOTS_CHECKLIST.md`
- `docs/SECURITY_MODEL.md`

## Reports And Artifacts

Public repo should exclude the current `reports/` contents by default because they contain captures, discovery outputs, and screenshots generated from private pilot work.

Only keep `reports/` content if it has been reviewed and anonymized for publication.

## General Rule

Keep source code, tests, templates, and documentation.

Do not publish runtime databases, logs, captures, screenshots, debug files, local environment files, or operational artifacts tied to private pilot infrastructure.
