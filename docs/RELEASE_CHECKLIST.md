# Release Checklist

Before tagging or publishing a portfolio release:

- Tests pass
- Frontend production build passes
- Alembic migrations pass from empty DB to head
- OpenAPI generation works
- Environment variables are documented
- Secrets are not committed
- `admin/admin` is documented as local/dev only
- JWT secret warning is visible in docs
- SMTP settings are documented
- Demo seed script works
- Screenshots are captured
- Deploy smoke test is completed
- Protected routes are still enforced
- Tenant isolation tests are still passing
- Resident/admin role separation is still covered

Suggested final smoke flow:

1. Run migrations on a fresh DB
2. Seed demo data
3. Log in as admin
4. Generate/inspect billing
5. Preview reminder / statement / receipt email flows
6. Import a CSV and download errors CSV if present
7. Log in as resident and verify resident-only visibility

