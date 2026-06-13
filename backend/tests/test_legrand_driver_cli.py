from __future__ import annotations

from condocharge.app.integrations.legrand.driver import (
    ChargingSession,
    LegrandGreenUpRfidStatus,
    LegrandGreenUpStationStatus,
)
from condocharge.tools.legrand_driver_test import _build_host_report, _render_terminal_summary


def test_build_host_report_shapes_json_without_password() -> None:
    session = ChargingSession(
        start_time="2026-06-09T12:00:00",
        end_time="2026-06-09T12:30:00",
        energy_wh=3500,
        total_minutes=30,
        charging_minutes=25,
        idle_minutes=5,
        plug_type="Type2",
        rfid_id="1234",
        rfid_name="Mario",
    )
    station_status = LegrandGreenUpStationStatus(
        state_text="Pronto per la ricarica",
        mode_text="Carico diretto",
        max_charging_current_a=32.0,
        instantaneous_current_a=0.0,
        instantaneous_power_kva=0.0,
    )
    rfid_status = LegrandGreenUpRfidStatus(
        station_state="Pronto per la ricarica",
        rfid_enabled=True,
        badge_programming_mode="Modo utilizzo",
    )

    report = _build_host_report(
        host="192.168.1.200",
        login_success=True,
        station_status=station_status,
        rfid_status=rfid_status,
        sessions=[session],
        errors=[],
    )

    assert set(report) == {
        "host",
        "login_success",
        "station_status",
        "rfid_status",
        "session_count",
        "total_energy_wh",
        "latest_session",
        "errors",
    }
    assert report["host"] == "192.168.1.200"
    assert report["login_success"] is True
    assert report["session_count"] == 1
    assert report["total_energy_wh"] == 3500
    assert report["latest_session"]["rfid_name"] == "Mario"
    assert "password" not in str(report).lower()


def test_render_terminal_summary_is_clean_and_password_free() -> None:
    report = {
        "generated_at": "2026-06-09T12:34:56+00:00",
        "targets": [
            {
                "host": "192.168.1.200",
                "login_success": True,
                "station_status": {
                    "connector_status": "available",
                    "state_text": "Pronto per la ricarica",
                    "mode_text": "Carico diretto",
                    "max_charging_current_a": 32.0,
                    "instantaneous_current_a": 0.0,
                    "instantaneous_power_kva": 0.0,
                },
                "rfid_status": {
                    "station_state": "Pronto per la ricarica",
                    "rfid_enabled": True,
                    "badge_programming_mode": "Modo utilizzo",
                },
                "session_count": 1,
                "total_energy_wh": 3500,
                "latest_session": {
                    "end_time": "2026-06-09T12:30:00",
                    "energy_wh": 3500,
                    "rfid_name": "Mario",
                },
                "errors": [],
            }
        ],
    }

    summary = _render_terminal_summary(report)

    assert "CondoCharge Legrand Driver Test" in summary
    assert "Host: 192.168.1.200" in summary
    assert "Login: OK" in summary
    assert "Sessions: count=1 | total_energy_wh=3500" in summary
    assert "Errors: none" in summary
    assert "password" not in summary.lower()

