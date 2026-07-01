# Archived\n\nStatus: Closed\n\nThis document is archived for internal reference and is not part of the public product documentation.\n\n---\n\n# Portfolio Notes

## Short Pitch

CondoCharge is a portfolio-ready multi-tenant EV charging operations platform for condominium environments. It covers the flow from charging-session ingestion to resident billing, payment reconciliation, and reminder operations.

## Why This Project Is Interesting

- Real integration work against Legrand Green'Up hardware endpoints
- End-to-end product slice across backend, frontend, persistence, auth, and billing
- Multi-tenant security and role-based access control
- Practical admin tooling instead of just a demo dashboard
- Operational workflows for billing, PDF statements, CSV imports, and email preview/send behavior

## Key Technical Highlights

- FastAPI + SQLAlchemy + Alembic backend
- React + TypeScript + Vite frontend
- JWT auth with tenant and role claims
- Deterministic billing and payment services
- Import job tracking with row-level results and unmatched queue
- Reminder rules and batch reminder execution
- Email preview mode for safe local and portfolio demos

## Strong Demo Paths

Recommended demo story:

1. Log in as admin
2. Show dashboard and resident management
3. Show RFID-to-resident assignment
4. Open cost report and billing period generation
5. Show resident statements and PDF export
6. Import a payments CSV and inspect import-job history
7. Show reminder candidates and run preview reminders
8. Show resident login and resident billing visibility

## What To Emphasize In Interviews

- Building a tenant-safe product, not just isolated features
- Choosing preview-first behavior for risky operational actions like email
- Maintaining append-only payment/audit history
- Designing current async workflows so they can later move to Celery/RQ/APScheduler
- Handling local development convenience without confusing it for production readiness

## What Is Intentionally Not Claimed

- This is not yet a fully production-hardened background-job platform
- In-process async tasks are suitable for demo/dev and architectural direction, not final scale
- SMTP and deployment need environment-specific production setup


