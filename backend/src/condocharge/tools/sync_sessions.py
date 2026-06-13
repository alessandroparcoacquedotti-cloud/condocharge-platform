from __future__ import annotations

import argparse
import sys

from sqlalchemy.exc import SQLAlchemyError

from condocharge.app.integrations.legrand.driver import LegrandGreenUpDriver
from condocharge.app.services.session_sync_service import SessionSyncService
from condocharge.db.session import SessionLocal

DEFAULT_HOSTS = ["192.168.1.200", "192.168.1.201"]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="sync_sessions",
        description="Sync Legrand Green'Up charging sessions into the CondoCharge database.",
        epilog=(
            "PowerShell example:\n"
            "  python -m condocharge.tools.sync_sessions "
            "--username admin --password '<SECRET>' "
            "--hosts 192.168.1.200 192.168.1.201"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--username", required=True, help="Station username")
    parser.add_argument("--password", required=True, help="Station password (never printed)")
    parser.add_argument("--hosts", nargs="*", default=DEFAULT_HOSTS, help="One or more station hosts")
    parser.add_argument("--condominium-id", type=int, default=1, help="Condominium ID to import data into")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    hosts = [h for h in list(dict.fromkeys(args.hosts)) if h and h.strip()]

    driver = LegrandGreenUpDriver()
    db = SessionLocal()
    try:
        service = SessionSyncService(db=db, driver=driver)
        result = service.sync_hosts(
            condominium_id=int(args.condominium_id),
            hosts=hosts,
            username=args.username,
            password=args.password,
        )
    except SQLAlchemyError as exc:
        print(f"Database error: {type(exc).__name__}: {exc}")
        print("Hint: run `alembic upgrade head` in backend/ to create the required tables.")
        return 2
    finally:
        try:
            db.close()
        finally:
            driver.close()

    print("CondoCharge Session Sync")
    print(f"Hosts: {', '.join(hosts) if hosts else '-'}")
    print(f"Sessions imported: {result.sessions_imported}")
    print(f"Sessions updated: {result.sessions_updated}")
    print(f"Total sessions: {result.total_sessions}")
    print(f"Total energy imported (Wh): {result.total_energy_imported_wh}")
    if result.errors:
        print("Errors:")
        for e in result.errors:
            print(f"  - {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
