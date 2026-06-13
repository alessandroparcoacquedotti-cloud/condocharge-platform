from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from condocharge.app.integrations.legrand.driver import (
    ChargingSession,
    LegrandGreenUpDriver,
    LegrandGreenUpRfidStatus,
    LegrandGreenUpStationStatus,
)


DEFAULT_HOSTS = ["192.168.1.200", "192.168.1.201"]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _json_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def _build_host_report(
    *,
    host: str,
    login_success: bool,
    station_status: LegrandGreenUpStationStatus | None,
    rfid_status: LegrandGreenUpRfidStatus | None,
    sessions: list[ChargingSession] | None,
    errors: list[str],
) -> dict[str, Any]:
    session_list = sessions or []
    total_energy_wh = sum(session.energy_wh for session in session_list)
    latest_session = max(session_list, key=lambda item: item.end_time) if session_list else None
    return {
        "host": host,
        "login_success": login_success,
        "station_status": _json_value(station_status) if station_status is not None else None,
        "rfid_status": _json_value(rfid_status) if rfid_status is not None else None,
        "session_count": len(session_list),
        "total_energy_wh": total_energy_wh,
        "latest_session": _json_value(latest_session) if latest_session is not None else None,
        "errors": errors,
    }


def _build_full_report(host_reports: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "targets": host_reports,
    }


def _host_summary_lines(host_report: dict[str, Any]) -> list[str]:
    station_status = host_report["station_status"]
    rfid_status = host_report["rfid_status"]
    latest_session = host_report["latest_session"]
    errors = host_report["errors"]

    lines = [
        f"Host: {host_report['host']}",
        f"  Login: {'OK' if host_report['login_success'] else 'FAILED'}",
    ]

    if station_status is not None:
        lines.extend(
            [
                f"  Station: {station_status.get('connector_status') or '-'}"
                f" | state={station_status.get('state_text') or '-'}"
                f" | mode={station_status.get('mode_text') or '-'}",
                f"  Electrical: max={station_status.get('max_charging_current_a')!s}A"
                f" | current={station_status.get('instantaneous_current_a')!s}A"
                f" | power={station_status.get('instantaneous_power_kva')!s}kVA",
            ]
        )
    else:
        lines.append("  Station: -")

    if rfid_status is not None:
        lines.append(
            f"  RFID: enabled={rfid_status.get('rfid_enabled')!s}"
            f" | mode={rfid_status.get('badge_programming_mode') or '-'}"
        )
    else:
        lines.append("  RFID: -")

    lines.append(
        f"  Sessions: count={host_report['session_count']}"
        f" | total_energy_wh={host_report['total_energy_wh']}"
    )

    if latest_session is not None:
        lines.append(
            f"  Latest session: end={latest_session.get('end_time') or '-'}"
            f" | energy_wh={latest_session.get('energy_wh')!s}"
            f" | rfid_name={latest_session.get('rfid_name') or '-'}"
        )
    else:
        lines.append("  Latest session: -")

    if errors:
        lines.append(f"  Errors: {'; '.join(errors)}")
    else:
        lines.append("  Errors: none")

    return lines


def _render_terminal_summary(report: dict[str, Any]) -> str:
    lines = [
        "CondoCharge Legrand Driver Test",
        f"Generated: {report['generated_at']}",
        "",
    ]
    targets = report.get("targets", [])
    for index, host_report in enumerate(targets):
        if index > 0:
            lines.append("")
        lines.extend(_host_summary_lines(host_report))
    return "\n".join(lines)


def _test_host(driver: LegrandGreenUpDriver, *, host: str, username: str, password: str) -> dict[str, Any]:
    login_success = False
    station_status: LegrandGreenUpStationStatus | None = None
    rfid_status: LegrandGreenUpRfidStatus | None = None
    sessions: list[ChargingSession] | None = None
    errors: list[str] = []

    try:
        driver.login(host, username, password)
        login_success = True
    except Exception as exc:
        errors.append(f"login: {type(exc).__name__}: {exc}")
        return _build_host_report(
            host=host,
            login_success=login_success,
            station_status=station_status,
            rfid_status=rfid_status,
            sessions=sessions,
            errors=errors,
        )

    try:
        station_status = driver.get_station_status(host)
    except Exception as exc:
        errors.append(f"station_status: {type(exc).__name__}: {exc}")

    try:
        rfid_status = driver.get_rfid_status(host)
    except Exception as exc:
        errors.append(f"rfid_status: {type(exc).__name__}: {exc}")

    try:
        csv_content = driver.download_charge_sessions(host)
        sessions = driver.parse_charge_session_csv(csv_content)
    except Exception as exc:
        errors.append(f"charge_sessions: {type(exc).__name__}: {exc}")

    return _build_host_report(
        host=host,
        login_success=login_success,
        station_status=station_status,
        rfid_status=rfid_status,
        sessions=sessions,
        errors=errors,
    )


def _write_report(report: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
        f.write("\n")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="legrand_driver_test",
        description="Exercise the real Legrand Green'Up driver against one or more stations.",
        epilog=(
            "PowerShell example:\n"
            "  python -m condocharge.tools.legrand_driver_test "
            "--username admin --password '<SECRET>' "
            "--hosts 192.168.1.200 192.168.1.201 "
            "--output ..\\reports\\legrand_driver_test_report.json"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--username", required=True, help="Station username")
    parser.add_argument("--password", required=True, help="Station password (never printed or stored)")
    parser.add_argument("--hosts", nargs="*", default=DEFAULT_HOSTS, help="One or more station hosts")
    parser.add_argument(
        "--output",
        default=str(_repo_root() / "reports" / "legrand_driver_test_report.json"),
        help="Path to the JSON report",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])

    driver = LegrandGreenUpDriver()
    try:
        host_reports = [
            _test_host(driver, host=host, username=args.username, password=args.password)
            for host in list(dict.fromkeys(args.hosts))
        ]
    finally:
        driver.close()

    report = _build_full_report(host_reports)
    output_path = Path(args.output)
    _write_report(report, output_path)

    print(_render_terminal_summary(report))
    print("")
    print(f"Report written to: {output_path}")

    return 0 if all(not item["errors"] for item in host_reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
