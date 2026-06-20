from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

EXPECTED_TABLES = (
    "charging_sessions",
    "charging_stations",
    "agent_states",
    "app_users",
)


@dataclass(slots=True)
class DatabaseInspection:
    db_path: str
    file_size_bytes: int
    sha256: str
    integrity_check: str
    row_counts: dict[str, int | None]
    missing_tables: list[str]
    alembic_version: str | None


def materialize_sqlite_snapshot(source_db_path: Path, snapshot_db_path: Path) -> Path:
    source_db_path = source_db_path.resolve()
    snapshot_db_path = snapshot_db_path.resolve()
    snapshot_db_path.parent.mkdir(parents=True, exist_ok=True)
    if snapshot_db_path.exists():
        snapshot_db_path.unlink()

    with sqlite3.connect(str(source_db_path)) as source_conn:
        with sqlite3.connect(str(snapshot_db_path)) as snapshot_conn:
            source_conn.backup(snapshot_conn)

    return snapshot_db_path


def inspect_database(db_path: Path) -> DatabaseInspection:
    resolved = db_path.resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"SQLite database not found: {resolved}")

    with sqlite3.connect(str(resolved)) as conn:
        integrity_check = str(conn.execute("PRAGMA integrity_check;").fetchone()[0])
        table_names = {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;").fetchall()
        }

        row_counts: dict[str, int | None] = {}
        missing_tables: list[str] = []
        for table_name in EXPECTED_TABLES:
            if table_name not in table_names:
                row_counts[table_name] = None
                missing_tables.append(table_name)
                continue
            row_counts[table_name] = int(conn.execute(f"SELECT COUNT(*) FROM {table_name};").fetchone()[0])

        alembic_version: str | None = None
        if "alembic_version" in table_names:
            row = conn.execute("SELECT version_num FROM alembic_version LIMIT 1;").fetchone()
            if row is not None:
                alembic_version = str(row[0])

    return DatabaseInspection(
        db_path=str(resolved),
        file_size_bytes=resolved.stat().st_size,
        sha256=_sha256_file(resolved),
        integrity_check=integrity_check,
        row_counts=row_counts,
        missing_tables=missing_tables,
        alembic_version=alembic_version,
    )


def build_manifest(
    *,
    db_path: Path,
    remote_db_path: str,
    volume_name: str,
    service_name: str,
    project_name: str,
    captured_at_utc: str,
) -> dict[str, Any]:
    inspection = inspect_database(db_path)
    return {
        "captured_at_utc": captured_at_utc,
        "remote_db_path": remote_db_path,
        "volume_name": volume_name,
        "service_name": service_name,
        "project_name": project_name,
        "inspection": asdict(inspection),
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        while True:
            chunk = file_handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SQLite backup helper for CondoCharge production backups.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    snapshot_parser = subparsers.add_parser("snapshot", help="Create a clean SQLite snapshot from a source DB.")
    snapshot_parser.add_argument("--source-db-path", required=True)
    snapshot_parser.add_argument("--snapshot-db-path", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="Inspect a SQLite DB and optionally write a manifest.")
    inspect_parser.add_argument("--db-path", required=True)
    inspect_parser.add_argument("--output-json")
    inspect_parser.add_argument("--remote-db-path", default="")
    inspect_parser.add_argument("--volume-name", default="")
    inspect_parser.add_argument("--service-name", default="")
    inspect_parser.add_argument("--project-name", default="")
    inspect_parser.add_argument("--captured-at", default=datetime.now(tz=UTC).isoformat())
    inspect_parser.add_argument("--require-ok", action="store_true")

    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.command == "snapshot":
        snapshot_path = materialize_sqlite_snapshot(
            source_db_path=Path(args.source_db_path),
            snapshot_db_path=Path(args.snapshot_db_path),
        )
        print(snapshot_path)
        return

    manifest = build_manifest(
        db_path=Path(args.db_path),
        remote_db_path=args.remote_db_path,
        volume_name=args.volume_name,
        service_name=args.service_name,
        project_name=args.project_name,
        captured_at_utc=args.captured_at,
    )
    if args.output_json:
        write_json(Path(args.output_json), manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    if args.require_ok and manifest["inspection"]["integrity_check"] != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
