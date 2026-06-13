# Remove From Repo

This file lists content that should be removed from the public GitHub repository before publication.

## Databases

- `backend/*.sqlite3`
- `frontend/*.sqlite3`

Examples currently present in the workspace:

- `backend/condocharge_dev.sqlite3`
- `backend/demo_screenshots.sqlite3`
- `backend/ops_validation.sqlite3`
- `backend/ops_validation_fix.sqlite3`
- `backend/ops_validation_real.sqlite3`
- `backend/pilot_real.sqlite3`
- `backend/pilot_real_absolute.sqlite3`
- `frontend/migration_smoke.sqlite3`

## Backups And SQLite Sidecars

- `backend/*.sqlite3-wal`
- `backend/*.sqlite3-shm`
- `backend/*.sqlite3.backup_*`

## Logs

- `backend/logs/*.log`
- generated helper scripts under `backend/logs/`

## Screenshots

- `reports/screenshots/`

## HAR Captures

- `reports/*.har`

## Discovery Reports And Captures

- `reports/*capture*.json`
- `reports/*discovery*.json`

## Debug Artifacts

- `.dbg/`
- `debug-*.md`

## Operational Scripts

Review before publication and remove if they remain tied to private pilot infrastructure, stored credentials, or private network hosts:

- `backend/ops/`
- `backend/logs/pilot_sync_sessions_runner.py`

## Remove-From-History Candidates

If any of the files above were ever committed, remove them from Git history before making the repository public.

## Notes

- Do not modify `pilot_real.sqlite3` in place as part of cleanup planning.
- The goal is to exclude private runtime artifacts from GitHub, not to change application behavior.
