from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PrivacyCheckResult:
    condominiums_non_demo: int
    users_non_demo_email: int
    users_non_demo_username: int
    rfid_non_demo: int
    stations_non_demo_host: int

    @property
    def ok(self) -> bool:
        return (
            self.condominiums_non_demo == 0
            and self.users_non_demo_email == 0
            and self.users_non_demo_username == 0
            and self.rfid_non_demo == 0
            and self.stations_non_demo_host == 0
        )


def _check(db_path: Path) -> PrivacyCheckResult:
    db = sqlite3.connect(str(db_path))
    cur = db.cursor()
    queries = {
        "condominiums_non_demo": (
            "select count(*) from condominiums "
            "where name not in ('Portfolio Demo Condominium', 'Default Condominium')"
        ),
        "users_non_demo_email": (
            "select count(*) from app_users "
            "where email is not null "
            "and email not like '%@example.com' "
            "and email not like '%@condocharge.local'"
        ),
        "users_non_demo_username": (
            "select count(*) from app_users "
            "where role='resident' "
            "and username not like 'demo_%'"
        ),
        "rfid_non_demo": "select count(*) from rfid_users where rfid_id not like 'DEMO-RFID-%'",
        "stations_non_demo_host": "select count(*) from charging_stations where host not like 'demo-station-%.local'",
    }
    results = {k: int(cur.execute(q).fetchone()[0]) for k, q in queries.items()}
    return PrivacyCheckResult(**results)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify demo DB contains only demo-safe values for screenshots.")
    parser.add_argument("--db", required=True, help="Path to the SQLite database file.")
    args = parser.parse_args()
    result = _check(Path(args.db).resolve())
    print("privacy_check:", result)
    print("privacy_ok:", result.ok)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
