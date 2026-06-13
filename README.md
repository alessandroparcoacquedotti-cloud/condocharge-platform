# CondoCharge

[![CI](https://github.com/alessandroparcoacquedotti-cloud/condocharge-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/alessandroparcoacquedotti-cloud/condocharge-platform/actions/workflows/ci.yml)

CondoCharge is a multi-tenant condominium EV charging management platform built for real-world operational workflows and portfolio presentation.

It combines:

- Resident charging and consumption visibility
- Admin cost accounting and resident assignment
- Billing periods and generated resident statements
- PDF statement export
- Payment reconciliation and CSV payment import
- Email reminder / receipt / statement preview and SMTP delivery flows
- Tenant isolation with role-based access control

![CondoCharge admin dashboard](docs/images/02-admin-dashboard.png)

## GitHub Metadata

Recommended GitHub repository description:

`Multi-tenant EV charging management platform with FastAPI, React, billing workflows, reconciliation, and resident/admin portals.`

Recommended GitHub topics:

- `fastapi`
- `react`
- `typescript`
- `vite`
- `sqlalchemy`
- `alembic`
- `multi-tenant`
- `ev-charging`
- `portfolio-project`

![CondoCharge resident dashboard](docs/images/03-resident-dashboard.png)

![CondoCharge billing workflow](docs/images/04-billing-reconciliation.png)

## Product Summary

CondoCharge helps a condominium operator manage shared EV charging infrastructure from imported charging sessions through billing and payment reconciliation.

Core capabilities:

- Multi-tenant condominium model with tenant-safe data isolation
- JWT-authenticated API with `admin`, `resident`, and `viewer` roles
- Resident dashboard for consumption history and billing visibility
- Admin tools for residents, RFID assignment, cost review, billing, reconciliation, reminders, and SMTP health
- Statement generation from charging sessions
- Payment records, partial payment support, unmatched payment queue, and import job history
- Deterministic email templates with preview mode when SMTP is disabled

## Architecture

- Backend: FastAPI application under `backend/src/condocharge`
- Frontend: React + TypeScript + Vite under `frontend/src`
- ORM / migrations: SQLAlchemy + Alembic
- Auth: JWT access tokens with tenant and role claims
- Domain services: billing, payment import, reminders, PDF generation, and email delivery

See:

- [ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [SECURITY_MODEL.md](docs/SECURITY_MODEL.md)
- [BILLING_FLOW.md](docs/BILLING_FLOW.md)
- [DEPLOYMENT.md](docs/DEPLOYMENT.md)
- [PORTFOLIO_NOTES.md](docs/PORTFOLIO_NOTES.md)
- [PORTFOLIO_IMPROVEMENTS.md](docs/PORTFOLIO_IMPROVEMENTS.md)

## Additional Docs

- [SCREENSHOTS_CHECKLIST.md](docs/SCREENSHOTS_CHECKLIST.md)

## Repo Layout

- `backend`: FastAPI app, services, Alembic migrations, tests, tools
- `frontend`: React SPA, admin and resident pages, API client
- `docs`: deployment, architecture, billing, security, release, and portfolio notes

## Local Startup

### Backend

```powershell
cd backend
python -m alembic upgrade head
python -m uvicorn condocharge.main:app --reload
```

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

### Demo Data

```powershell
cd backend
python -m condocharge.tools.demo_seed
```

This adds demo/dev-only data without deleting existing data.

## Tests And Verification

### Backend Tests

```powershell
cd backend
python -m pytest
```

### Frontend Production Build

```powershell
cd frontend
npm run build
```

### Migration Smoke Test From Empty SQLite DB

```powershell
cd backend
$env:CONDOCHARGE_DATABASE_URL='sqlite+pysqlite:///./migration_smoke.sqlite3'
python -m alembic upgrade head
```

## Environment Variables

Required or important runtime settings are documented in:

- `.env.example`
- [DEPLOYMENT.md](docs/DEPLOYMENT.md)

Key settings:

- `CONDOCHARGE_DATABASE_URL`
- `CONDOCHARGE_JWT_SECRET_KEY`
- `CONDOCHARGE_CORS_ORIGINS`
- `CONDOCHARGE_EMAIL_ENABLED`
- `CONDOCHARGE_EMAIL_FROM`
- `CONDOCHARGE_SMTP_HOST`
- `CONDOCHARGE_SMTP_PORT`
- `CONDOCHARGE_SMTP_USERNAME`
- `CONDOCHARGE_SMTP_PASSWORD`
- `CONDOCHARGE_SMTP_USE_TLS`

## Local Dev Defaults Warning

- The seeded `admin/admin` account is for local development convenience only.
- Production must use a strong JWT secret.
- Production must use a non-default admin password.
- SMTP credentials and secrets must never be committed.

## Roadmap

- Durable async worker execution for import and reminder jobs
- Scheduled reminder automation with persisted run history
- Real SMTP integration verification in staging
- Statement-send / retry UX polish and operational audit export
- Production deployment templates and smoke-test automation
