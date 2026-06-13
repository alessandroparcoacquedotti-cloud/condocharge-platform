# Security Model

## Tenant Isolation

CondoCharge is designed as a multi-tenant application where each condominium is a data boundary.

Isolation rules:

- Every `AppUser` belongs to exactly one `Condominium`
- Charging, billing, payment, import, and reminder workflows are condominium-scoped
- Admin APIs only return data from the authenticated admin's condominium
- Resident APIs only return data for the authenticated resident in their own condominium

## Authentication

- FastAPI issues JWT access tokens after successful login
- Token payload includes:
  - user id
  - condominium id
  - role
  - expiration

## Authorization

Roles:

- `admin`: full administrative access within one condominium
- `resident`: resident self-service visibility only
- `viewer`: limited read-only/admin-side visibility where allowed

Protected-route expectations:

- Admin billing, residents, reconciliation, reminder, and email routes are admin-only
- Resident billing and resident dashboard routes are resident-only
- Cross-tenant object access returns not-found style behavior where appropriate

## Passwords

- Passwords are stored as PBKDF2-SHA256 hashes
- Local/dev setup includes a seeded `admin/admin` account for convenience only
- Production must use a non-default admin password

## Secrets

Required production secrets:

- `CONDOCHARGE_JWT_SECRET_KEY`
- SMTP credentials when email sending is enabled
- database credentials when using PostgreSQL or another external DB

Rules:

- Never commit secrets into the repository
- Never deploy with `change-me` as JWT secret
- Rotate secrets outside source control

## Email Safety

- Email can be disabled globally with `CONDOCHARGE_EMAIL_ENABLED=false`
- When disabled, reminder/receipt/statement actions return preview payloads and still record notification history
- SMTP health endpoint does not expose passwords or secret values

## Operational Notes

- Import jobs, notifications, and reminders are audit-friendly and tenant-scoped
- Retry creates a new linked notification row rather than mutating history
- Current async-style jobs run in-process; production hardening should move them to a durable worker

## Current Risks To Address In Production

- Replace the dev JWT secret with a strong random secret
- Replace default local admin credentials
- Restrict CORS to known frontend origins
- Run behind HTTPS and a production-grade reverse proxy
- Move async jobs to a durable worker/scheduler before high-volume production use

