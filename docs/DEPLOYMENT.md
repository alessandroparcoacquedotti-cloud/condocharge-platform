# Deployment

## Runtime Requirements

- Python 3.12
- Node.js 20
- SQLite for local/dev or PostgreSQL for production-style deployment

## Required Environment Variables

Backend:

- `CONDOCHARGE_DATABASE_URL`
- `CONDOCHARGE_JWT_SECRET_KEY`
- `CONDOCHARGE_JWT_ALGORITHM`
- `CONDOCHARGE_JWT_ACCESS_TOKEN_EXPIRES_MINUTES`
- `CONDOCHARGE_CORS_ORIGINS`
- `CONDOCHARGE_EMAIL_ENABLED`
- `CONDOCHARGE_EMAIL_FROM`
- `CONDOCHARGE_SMTP_HOST`
- `CONDOCHARGE_SMTP_PORT`
- `CONDOCHARGE_SMTP_USERNAME`
- `CONDOCHARGE_SMTP_PASSWORD`
- `CONDOCHARGE_SMTP_USE_TLS`

Frontend:

- `VITE_API_BASE_URL`

## Production Warnings

- Do not deploy with `CONDOCHARGE_JWT_SECRET_KEY=change-me`
- Do not rely on `admin/admin` outside local development
- Change the default or demo admin password before any real deployment
- Do not commit SMTP or DB secrets
- Use exact `CONDOCHARGE_CORS_ORIGINS` values for browser clients; do not use `*` in pilot/production

## Local Development

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

## Docker Compose

The repository includes `docker-compose.yml` for local container orchestration:

- `api`
- `web`
- `db`

Example:

```powershell
docker compose up --build
```

## Migration Verification

Fresh DB smoke test:

```powershell
cd backend
$env:CONDOCHARGE_DATABASE_URL='sqlite+pysqlite:///./migration_smoke.sqlite3'
python -m alembic upgrade head
```

## SQLite Backup And Restore

Example pilot DB path:

- `<repo-root>/backend/pilot.sqlite3`

Timestamped backup naming currently used:

- `<repo-root>/backend/pilot.sqlite3.backup_YYYYMMDD_HHMMSS`

### Backup Procedure

Stop the backend before taking a filesystem copy:

```powershell
cd backend
$ts = Get-Date -Format 'yyyyMMdd_HHmmss'
$src = '.\pilot.sqlite3'
$dst = ".\pilot.sqlite3.backup_$ts"
Copy-Item -LiteralPath $src -Destination $dst -Force
Get-Item $src, $dst | Select-Object FullName, Length, LastWriteTime
```

Verify the SQLite file before or after backup:

```powershell
cd backend
python -c "import sqlite3; db=r'.\\pilot.sqlite3'; con=sqlite3.connect(db); print(con.execute('PRAGMA integrity_check').fetchall())"
```

### Restore Procedure

Stop the backend first, then restore from a known-good backup:

```powershell
cd backend
$backup = '.\pilot.sqlite3.backup_YYYYMMDD_HHMMSS'
$target = '.\pilot.sqlite3'
Copy-Item -LiteralPath $backup -Destination $target -Force
Get-Item $backup, $target | Select-Object FullName, Length, LastWriteTime
```

Run schema and integrity verification after restore:

```powershell
cd backend
$env:CONDOCHARGE_DATABASE_URL='sqlite+pysqlite:///./pilot.sqlite3'
python -m alembic upgrade head
python -c "import sqlite3; db=r'.\\pilot.sqlite3'; con=sqlite3.connect(db); print(con.execute('PRAGMA integrity_check').fetchall())"
```

Recommended smoke checks after restore:

```powershell
cd backend
$env:CONDOCHARGE_ENV='pilot'
$env:CONDOCHARGE_DATABASE_URL='sqlite+pysqlite:///./pilot.sqlite3'
$env:CONDOCHARGE_JWT_SECRET_KEY='replace-with-a-strong-32-byte-secret'
python -m uvicorn condocharge.main:app --host 0.0.0.0 --port 8000
```

## Build And Test

```powershell
cd backend
python -m pytest
```

```powershell
cd frontend
npm run build
```

## Recommended Production Hardening

- Put the API behind HTTPS and a reverse proxy
- Use PostgreSQL instead of SQLite
- Restrict CORS to exact frontend origins
- Store secrets in environment or secret manager only
- Move in-process async job handling to a durable worker system
- Add deployment smoke tests and monitoring
