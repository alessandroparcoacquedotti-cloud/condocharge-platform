from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
import os

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from condocharge.api.deps import get_db_session
from condocharge.core.config import get_settings
from condocharge.core.security import hash_password
from condocharge.db.base import Base
from condocharge.main import create_app
from condocharge.models.charging import ChargingSession, ChargingStation, RfidUser
from condocharge.models.tenancy import AppUser, Condominium


def _build_client() -> TestClient:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)
    Base.metadata.create_all(bind=engine)

    with TestingSessionLocal() as db:
        condo_a = Condominium(name="Condo A", energy_price_eur_per_kwh=0.40)
        condo_b = Condominium(name="Condo B", energy_price_eur_per_kwh=0.60)
        db.add_all([condo_a, condo_b])
        db.flush()

        admin_a = AppUser(
            condominium_id=condo_a.id,
            username="admin_a",
            password_hash=hash_password("password123"),
            role="admin",
            is_active=1,
        )
        resident_a1 = AppUser(
            condominium_id=condo_a.id,
            username="resident_a1",
            email="resident1@example.com",
            password_hash=hash_password("password123"),
            role="resident",
            is_active=1,
        )
        resident_a2 = AppUser(
            condominium_id=condo_a.id,
            username="resident_a2",
            email="resident2@example.com",
            password_hash=hash_password("password123"),
            role="resident",
            is_active=1,
        )
        admin_b = AppUser(
            condominium_id=condo_b.id,
            username="admin_b",
            password_hash=hash_password("password123"),
            role="admin",
            is_active=1,
        )
        db.add_all([admin_a, resident_a1, resident_a2, admin_b])
        db.flush()

        station_a = ChargingStation(condominium_id=condo_a.id, host="192.168.1.200", vendor="legrand_greenup", name="A")
        station_b = ChargingStation(condominium_id=condo_b.id, host="10.0.0.10", vendor="legrand_greenup", name="B")
        db.add_all([station_a, station_b])
        db.flush()

        card_a1 = RfidUser(condominium_id=condo_a.id, app_user_id=resident_a1.id, rfid_id="RFID-A1", name="Card A1")
        card_a2 = RfidUser(condominium_id=condo_a.id, app_user_id=resident_a2.id, rfid_id="RFID-A2", name="Card A2")
        card_unassigned = RfidUser(condominium_id=condo_a.id, rfid_id="RFID-U1", name="Unassigned")
        card_b1 = RfidUser(condominium_id=condo_b.id, rfid_id="RFID-B1", name="Other")
        db.add_all([card_a1, card_a2, card_unassigned, card_b1])
        db.flush()

        db.add_all(
            [
                ChargingSession(
                    condominium_id=condo_a.id,
                    source_key="a1",
                    station_id=station_a.id,
                    rfid_user_id=card_a1.id,
                    start_time=datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc),
                    end_time=datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
                    energy_wh=10000,
                    total_minutes=60,
                    charging_minutes=55,
                    idle_minutes=5,
                    plug_type="Type2",
                ),
                ChargingSession(
                    condominium_id=condo_a.id,
                    source_key="a2",
                    station_id=station_a.id,
                    rfid_user_id=card_a2.id,
                    start_time=datetime(2026, 6, 5, 18, 0, tzinfo=timezone.utc),
                    end_time=datetime(2026, 6, 5, 19, 0, tzinfo=timezone.utc),
                    energy_wh=4000,
                    total_minutes=60,
                    charging_minutes=60,
                    idle_minutes=0,
                    plug_type="Type2",
                ),
                ChargingSession(
                    condominium_id=condo_a.id,
                    source_key="a3",
                    station_id=station_a.id,
                    rfid_user_id=card_unassigned.id,
                    start_time=datetime(2026, 6, 7, 12, 0, tzinfo=timezone.utc),
                    end_time=datetime(2026, 6, 7, 13, 0, tzinfo=timezone.utc),
                    energy_wh=3000,
                    total_minutes=60,
                    charging_minutes=50,
                    idle_minutes=10,
                    plug_type="Type2",
                ),
                ChargingSession(
                    condominium_id=condo_b.id,
                    source_key="b1",
                    station_id=station_b.id,
                    rfid_user_id=card_b1.id,
                    start_time=datetime(2026, 6, 3, 8, 0, tzinfo=timezone.utc),
                    end_time=datetime(2026, 6, 3, 9, 0, tzinfo=timezone.utc),
                    energy_wh=9000,
                    total_minutes=60,
                    charging_minutes=60,
                    idle_minutes=0,
                    plug_type="Type2",
                ),
            ]
        )
        db.commit()

    app = create_app()

    def override_get_db_session() -> Iterator[Session]:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db_session] = override_get_db_session
    return TestClient(app)


def _login(client: TestClient, *, username: str, condominium: str) -> dict[str, str]:
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "password123", "condominium": condominium},
    )
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['token']['access_token']}"}


def _create_period(client: TestClient, headers: dict[str, str]) -> int:
    resp = client.post(
        "/api/v1/admin/billing/periods",
        json={
            "name": "June 2026",
            "period_start": "2026-06-01T00:00:00Z",
            "period_end": "2026-06-30T23:59:59Z",
        },
        headers=headers,
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def _create_custom_period(
    client: TestClient,
    headers: dict[str, str],
    *,
    name: str,
    period_start: str,
    period_end: str,
):
    return client.post(
        "/api/v1/admin/billing/periods",
        json={"name": name, "period_start": period_start, "period_end": period_end},
        headers=headers,
    )


def _set_email_enabled(enabled: bool) -> None:
    os.environ["CONDOCHARGE_EMAIL_ENABLED"] = "true" if enabled else "false"
    get_settings.cache_clear()


def test_admin_creates_billing_period_and_other_condo_cannot_access_it() -> None:
    client = _build_client()
    admin_a_headers = _login(client, username="admin_a", condominium="Condo A")
    admin_b_headers = _login(client, username="admin_b", condominium="Condo B")

    period_id = _create_period(client, admin_a_headers)

    detail = client.get(f"/api/v1/admin/billing/periods/{period_id}", headers=admin_a_headers)
    assert detail.status_code == 200
    assert detail.json()["name"] == "June 2026"

    forbidden = client.get(f"/api/v1/admin/billing/periods/{period_id}", headers=admin_b_headers)
    assert forbidden.status_code == 404


def test_email_field_validation_works() -> None:
    client = _build_client()
    admin_headers = _login(client, username="admin_a", condominium="Condo A")
    resp = client.post(
        "/api/v1/admin/residents",
        json={
            "first_name": "Mario",
            "last_name": "Rossi",
            "apartment_or_unit": "A-9",
            "email": "not-an-email",
            "phone_number": None,
        },
        headers=admin_headers,
    )
    assert resp.status_code == 422


def test_overlapping_periods_rejected_adjacent_allowed_and_invalid_ranges_rejected() -> None:
    client = _build_client()
    admin_a_headers = _login(client, username="admin_a", condominium="Condo A")

    first = _create_custom_period(
        client,
        admin_a_headers,
        name="Window 1",
        period_start="2026-06-01T00:00:00Z",
        period_end="2026-06-10T00:00:00Z",
    )
    assert first.status_code == 201

    overlap = _create_custom_period(
        client,
        admin_a_headers,
        name="Overlap",
        period_start="2026-06-09T12:00:00Z",
        period_end="2026-06-11T00:00:00Z",
    )
    assert overlap.status_code == 400
    assert "overlaps" in overlap.json()["detail"].lower()

    adjacent = _create_custom_period(
        client,
        admin_a_headers,
        name="Adjacent",
        period_start="2026-06-10T00:00:00Z",
        period_end="2026-06-20T00:00:00Z",
    )
    assert adjacent.status_code == 201

    invalid = _create_custom_period(
        client,
        admin_a_headers,
        name="Invalid",
        period_start="2026-06-20T00:00:00Z",
        period_end="2026-06-20T00:00:00Z",
    )
    assert invalid.status_code == 400
    assert "greater than" in invalid.json()["detail"].lower()


def test_statement_generation_snapshot_and_unassigned_usage_are_correct() -> None:
    client = _build_client()
    admin_a_headers = _login(client, username="admin_a", condominium="Condo A")
    period_id = _create_period(client, admin_a_headers)

    generated = client.post(f"/api/v1/admin/billing/periods/{period_id}/generate", headers=admin_a_headers)
    assert generated.status_code == 200
    payload = generated.json()
    assert payload["energy_price_eur_per_kwh_snapshot"] == 0.4
    assert payload["unassigned_sessions_count"] == 1
    assert payload["unassigned_energy_kwh"] == 3.0
    assert payload["unassigned_amount_eur"] == 1.2
    assert len(payload["statements"]) == 2

    resident1 = next(s for s in payload["statements"] if s["resident_username"] == "resident_a1")
    resident2 = next(s for s in payload["statements"] if s["resident_username"] == "resident_a2")
    assert resident1["statement_number"].startswith("CC-2026-")
    assert resident2["statement_number"].startswith("CC-2026-")
    assert resident1["statement_number"] != resident2["statement_number"]
    assert resident1["payment_reference"].startswith("PAY-CC-2026-")
    assert resident1["sessions_count"] == 1
    assert resident1["energy_kwh"] == 10.0
    assert resident1["amount_eur"] == 4.0
    assert resident2["sessions_count"] == 1
    assert resident2["energy_kwh"] == 4.0
    assert resident2["amount_eur"] == 1.6

    client.patch("/api/v1/admin/settings", json={"energy_price_eur_per_kwh": 0.55}, headers=admin_a_headers)
    detail_after_price_change = client.get(f"/api/v1/admin/billing/periods/{period_id}", headers=admin_a_headers)
    assert detail_after_price_change.status_code == 200
    assert detail_after_price_change.json()["energy_price_eur_per_kwh_snapshot"] == 0.4
    assert next(s for s in detail_after_price_change.json()["statements"] if s["resident_username"] == "resident_a1")["amount_eur"] == 4.0


def test_closed_period_cannot_be_regenerated_and_historical_amounts_do_not_change() -> None:
    client = _build_client()
    admin_a_headers = _login(client, username="admin_a", condominium="Condo A")
    period_id = _create_period(client, admin_a_headers)

    generate = client.post(f"/api/v1/admin/billing/periods/{period_id}/generate", headers=admin_a_headers)
    assert generate.status_code == 200

    close = client.post(f"/api/v1/admin/billing/periods/{period_id}/close", headers=admin_a_headers)
    assert close.status_code == 200
    assert close.json()["status"] == "closed"

    client.patch("/api/v1/admin/settings", json={"energy_price_eur_per_kwh": 0.9}, headers=admin_a_headers)
    detail = client.get(f"/api/v1/admin/billing/periods/{period_id}", headers=admin_a_headers)
    assert detail.status_code == 200
    assert detail.json()["energy_price_eur_per_kwh_snapshot"] == 0.4
    assert next(s for s in detail.json()["statements"] if s["resident_username"] == "resident_a1")["amount_eur"] == 4.0

    regenerate = client.post(f"/api/v1/admin/billing/periods/{period_id}/generate", headers=admin_a_headers)
    assert regenerate.status_code == 400


def test_statement_numbers_and_payment_references_are_unique_and_immutable() -> None:
    client = _build_client()
    admin_a_headers = _login(client, username="admin_a", condominium="Condo A")
    period_id = _create_period(client, admin_a_headers)

    first_generate = client.post(f"/api/v1/admin/billing/periods/{period_id}/generate", headers=admin_a_headers)
    assert first_generate.status_code == 200
    original = {s["resident_username"]: (s["statement_number"], s["payment_reference"]) for s in first_generate.json()["statements"]}

    regenerate = client.post(f"/api/v1/admin/billing/periods/{period_id}/generate", headers=admin_a_headers)
    assert regenerate.status_code == 200
    regenerated = {s["resident_username"]: (s["statement_number"], s["payment_reference"]) for s in regenerate.json()["statements"]}
    assert regenerated == original


def test_resident_only_sees_own_statements_and_cannot_use_admin_billing_apis() -> None:
    client = _build_client()
    admin_a_headers = _login(client, username="admin_a", condominium="Condo A")
    resident1_headers = _login(client, username="resident_a1", condominium="Condo A")
    resident2_headers = _login(client, username="resident_a2", condominium="Condo A")
    period_id = _create_period(client, admin_a_headers)
    generated = client.post(f"/api/v1/admin/billing/periods/{period_id}/generate", headers=admin_a_headers)
    assert generated.status_code == 200
    statements = generated.json()["statements"]
    resident1_statement_id = next(s["id"] for s in statements if s["resident_username"] == "resident_a1")
    resident2_statement_id = next(s["id"] for s in statements if s["resident_username"] == "resident_a2")

    resident1_list = client.get("/api/v1/resident/billing/statements", headers=resident1_headers)
    assert resident1_list.status_code == 200
    assert len(resident1_list.json()) == 1
    assert resident1_list.json()[0]["resident_username"] == "resident_a1"

    resident1_detail = client.get(f"/api/v1/resident/billing/statements/{resident1_statement_id}", headers=resident1_headers)
    assert resident1_detail.status_code == 200
    assert resident1_detail.json()["sessions_count"] == 1
    assert len(resident1_detail.json()["sessions"]) == 1

    forbidden_other = client.get(f"/api/v1/resident/billing/statements/{resident2_statement_id}", headers=resident1_headers)
    assert forbidden_other.status_code == 404

    forbidden_admin = client.get("/api/v1/admin/billing/periods", headers=resident2_headers)
    assert forbidden_admin.status_code == 403

    forbidden_pdf = client.get(
        f"/api/v1/resident/billing/statements/{resident2_statement_id}/export.pdf",
        headers=resident1_headers,
    )
    assert forbidden_pdf.status_code == 404


def test_billing_csv_export_and_payment_status_updates() -> None:
    client = _build_client()
    admin_a_headers = _login(client, username="admin_a", condominium="Condo A")
    period_id = _create_period(client, admin_a_headers)
    generated = client.post(f"/api/v1/admin/billing/periods/{period_id}/generate", headers=admin_a_headers)
    assert generated.status_code == 200
    resident1_statement_id = next(s["id"] for s in generated.json()["statements"] if s["resident_username"] == "resident_a1")

    updated = client.patch(
        f"/api/v1/admin/billing/statements/{resident1_statement_id}/payment-status",
        json={"payment_status": "paid", "note": "Bank transfer received"},
        headers=admin_a_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["payment_status"] == "paid"
    assert updated.json()["paid_at"] is not None

    detail = client.get(f"/api/v1/admin/billing/statements/{resident1_statement_id}", headers=admin_a_headers)
    assert detail.status_code == 200
    assert detail.json()["statement_number"].startswith("CC-2026-")
    assert detail.json()["payment_reference"].startswith("PAY-CC-2026-")
    assert len(detail.json()["payment_history"]) == 1
    assert detail.json()["payment_history"][0]["old_status"] == "unpaid"
    assert detail.json()["payment_history"][0]["new_status"] == "paid"
    assert detail.json()["payment_history"][0]["note"] == "Bank transfer received"

    csv_resp = client.get(f"/api/v1/admin/billing/periods/{period_id}/export.csv", headers=admin_a_headers)
    assert csv_resp.status_code == 200
    assert csv_resp.headers["content-type"].startswith("text/csv")
    body = csv_resp.text
    assert "period,resident,sessions_count,energy_kwh,amount_eur,payment_status,period_start,period_end" in body
    assert "June 2026,resident_a1,1,10.000,4.00,paid" in body
    assert "June 2026,resident_a2,1,4.000,1.60,unpaid" in body
    assert "June 2026,Unassigned,1,3.000,1.20," in body


def test_pdf_exports_and_settlement_summary() -> None:
    client = _build_client()
    admin_a_headers = _login(client, username="admin_a", condominium="Condo A")
    admin_b_headers = _login(client, username="admin_b", condominium="Condo B")
    resident1_headers = _login(client, username="resident_a1", condominium="Condo A")
    period_id = _create_period(client, admin_a_headers)
    generated = client.post(f"/api/v1/admin/billing/periods/{period_id}/generate", headers=admin_a_headers)
    assert generated.status_code == 200
    resident1_statement_id = next(s["id"] for s in generated.json()["statements"] if s["resident_username"] == "resident_a1")
    resident2_statement_id = next(s["id"] for s in generated.json()["statements"] if s["resident_username"] == "resident_a2")

    admin_pdf = client.get(f"/api/v1/admin/billing/statements/{resident1_statement_id}/export.pdf", headers=admin_a_headers)
    assert admin_pdf.status_code == 200
    assert admin_pdf.headers["content-type"].startswith("application/pdf")
    assert admin_pdf.content.startswith(b"%PDF")

    resident_pdf = client.get(f"/api/v1/resident/billing/statements/{resident1_statement_id}/export.pdf", headers=resident1_headers)
    assert resident_pdf.status_code == 200
    assert resident_pdf.headers["content-type"].startswith("application/pdf")

    forbidden_admin_pdf = client.get(f"/api/v1/admin/billing/statements/{resident1_statement_id}/export.pdf", headers=admin_b_headers)
    assert forbidden_admin_pdf.status_code == 404

    forbidden_resident_pdf = client.get(f"/api/v1/resident/billing/statements/{resident2_statement_id}/export.pdf", headers=resident1_headers)
    assert forbidden_resident_pdf.status_code == 404

    client.patch(
        f"/api/v1/admin/billing/statements/{resident1_statement_id}/payment-status",
        json={"payment_status": "paid", "note": "Paid"},
        headers=admin_a_headers,
    )
    client.patch(
        f"/api/v1/admin/billing/statements/{resident2_statement_id}/payment-status",
        json={"payment_status": "waived", "note": "Waived"},
        headers=admin_a_headers,
    )

    settlement = client.get("/api/v1/admin/billing/settlement/summary", headers=admin_a_headers)
    assert settlement.status_code == 200
    payload = settlement.json()
    assert payload["total_billed_eur"] == 5.6
    assert payload["paid_eur"] == 4.0
    assert payload["unpaid_eur"] == 0.0
    assert payload["waived_eur"] == 1.6
    assert payload["partially_paid_eur"] == 0.0
    assert payload["collection_rate"] == 71.43
    assert payload["open_periods"] == 1
    assert payload["closed_periods"] == 0


def test_partial_payments_status_append_only_reminder_and_reconciliation() -> None:
    client = _build_client()
    admin_a_headers = _login(client, username="admin_a", condominium="Condo A")
    admin_b_headers = _login(client, username="admin_b", condominium="Condo B")
    resident1_headers = _login(client, username="resident_a1", condominium="Condo A")
    period_id = _create_period(client, admin_a_headers)
    generated = client.post(f"/api/v1/admin/billing/periods/{period_id}/generate", headers=admin_a_headers)
    assert generated.status_code == 200
    resident1_statement_id = next(s["id"] for s in generated.json()["statements"] if s["resident_username"] == "resident_a1")
    resident2_statement_id = next(s["id"] for s in generated.json()["statements"] if s["resident_username"] == "resident_a2")

    resident_forbidden = client.post(
        f"/api/v1/admin/billing/statements/{resident1_statement_id}/payments",
        json={
            "amount_eur": 1.0,
            "method": "bank_transfer",
            "transaction_reference": "TX1",
            "note": "Test",
            "received_at": "2026-06-10T10:00:00Z",
        },
        headers=resident1_headers,
    )
    assert resident_forbidden.status_code == 403

    other_condo_forbidden = client.post(
        f"/api/v1/admin/billing/statements/{resident1_statement_id}/payments",
        json={
            "amount_eur": 1.0,
            "method": "bank_transfer",
            "transaction_reference": "TX1",
            "note": "Test",
            "received_at": "2026-06-10T10:00:00Z",
        },
        headers=admin_b_headers,
    )
    assert other_condo_forbidden.status_code == 404

    added = client.post(
        f"/api/v1/admin/billing/statements/{resident1_statement_id}/payments",
        json={
            "amount_eur": 1.0,
            "method": "bank_transfer",
            "transaction_reference": "TX1",
            "note": "Partial payment",
            "received_at": "2026-06-10T10:00:00Z",
        },
        headers=admin_a_headers,
    )
    assert added.status_code == 201

    detail_after_partial = client.get(f"/api/v1/admin/billing/statements/{resident1_statement_id}", headers=admin_a_headers)
    assert detail_after_partial.status_code == 200
    payload = detail_after_partial.json()
    assert payload["amount_eur"] == 4.0
    assert payload["amount_paid_eur"] == 1.0
    assert payload["amount_due_eur"] == 3.0
    assert payload["payment_status"] == "partially_paid"
    assert len(payload["payments"]) == 1

    payments_list = client.get(f"/api/v1/admin/billing/statements/{resident1_statement_id}/payments", headers=admin_a_headers)
    assert payments_list.status_code == 200
    assert len(payments_list.json()) == 1
    assert payments_list.json()[0]["transaction_reference"] == "TX1"

    added2 = client.post(
        f"/api/v1/admin/billing/statements/{resident1_statement_id}/payments",
        json={
            "amount_eur": 3.0,
            "method": "cash",
            "transaction_reference": "TX2",
            "note": "Second payment",
            "received_at": "2026-06-11T10:00:00Z",
        },
        headers=admin_a_headers,
    )
    assert added2.status_code == 201

    detail_after_full = client.get(f"/api/v1/admin/billing/statements/{resident1_statement_id}", headers=admin_a_headers)
    assert detail_after_full.status_code == 200
    assert detail_after_full.json()["payment_status"] == "paid"
    assert detail_after_full.json()["amount_due_eur"] == 0.0
    assert len(detail_after_full.json()["payments"]) == 2

    resident1_detail = client.get(f"/api/v1/resident/billing/statements/{resident1_statement_id}", headers=resident1_headers)
    assert resident1_detail.status_code == 200
    assert resident1_detail.json()["resident_username"] == "resident_a1"
    assert len(resident1_detail.json()["payments"]) == 2

    reminder = client.post(
        f"/api/v1/admin/billing/statements/{resident1_statement_id}/reminder",
        headers=admin_a_headers,
    )
    assert reminder.status_code == 200
    reminder_payload = reminder.json()
    assert reminder_payload["statement_number"].startswith("CC-2026-")
    assert reminder_payload["payment_reference"].startswith("PAY-CC-2026-")
    assert reminder_payload["period"] == "June 2026"

    detail_after_reminder = client.get(f"/api/v1/admin/billing/statements/{resident1_statement_id}", headers=admin_a_headers)
    assert detail_after_reminder.status_code == 200
    assert detail_after_reminder.json()["reminder_count"] == 1
    assert detail_after_reminder.json()["last_reminder_at"] is not None

    reconciliation = client.get(
        "/api/v1/admin/billing/reconciliation",
        params={"period_id": period_id},
        headers=admin_a_headers,
    )
    assert reconciliation.status_code == 200
    rec = reconciliation.json()
    assert rec["total_amount_eur"] == 5.6
    assert rec["total_paid_eur"] == 4.0
    assert rec["total_due_eur"] == 1.6


def test_reminder_with_email_disabled_creates_preview_notification() -> None:
    _set_email_enabled(False)
    client = _build_client()
    admin_headers = _login(client, username="admin_a", condominium="Condo A")
    period_id = _create_period(client, admin_headers)
    generated = client.post(f"/api/v1/admin/billing/periods/{period_id}/generate", headers=admin_headers)
    statement_id = generated.json()["statements"][0]["id"]

    reminder = client.post(f"/api/v1/admin/billing/statements/{statement_id}/reminder", headers=admin_headers)
    assert reminder.status_code == 200
    payload = reminder.json()
    assert payload["email_enabled"] is False
    assert payload["delivery_status"] == "preview"

    detail = client.get(f"/api/v1/admin/billing/statements/{statement_id}", headers=admin_headers)
    assert detail.status_code == 200
    assert len(detail.json()["notifications"]) == 1
    assert detail.json()["notifications"][0]["status"] == "preview"


def test_resident_cannot_access_notification_records() -> None:
    _set_email_enabled(False)
    client = _build_client()
    admin_headers = _login(client, username="admin_a", condominium="Condo A")
    resident_headers = _login(client, username="resident_a1", condominium="Condo A")
    period_id = _create_period(client, admin_headers)
    generated = client.post(f"/api/v1/admin/billing/periods/{period_id}/generate", headers=admin_headers)
    statement = next(s for s in generated.json()["statements"] if s["resident_username"] == "resident_a1")

    reminder = client.post(f"/api/v1/admin/billing/statements/{statement['id']}/reminder", headers=admin_headers)
    assert reminder.status_code == 200

    resident_detail = client.get(f"/api/v1/resident/billing/statements/{statement['id']}", headers=resident_headers)
    assert resident_detail.status_code == 200
    payload = resident_detail.json()
    assert "notifications" not in payload or payload["notifications"] == []


def test_reminder_with_missing_email_and_email_enabled_fails_clearly() -> None:
    _set_email_enabled(True)
    os.environ["CONDOCHARGE_SMTP_HOST"] = "localhost"
    get_settings.cache_clear()
    client = _build_client()
    admin_headers = _login(client, username="admin_a", condominium="Condo A")
    period_id = _create_period(client, admin_headers)
    generated = client.post(f"/api/v1/admin/billing/periods/{period_id}/generate", headers=admin_headers)
    first_statement = generated.json()["statements"][0]
    statement_id = first_statement["id"]

    client.patch(
        f"/api/v1/admin/residents/{first_statement['resident_app_user_id']}",
        json={"email": None},
        headers=admin_headers,
    )

    failed = client.post(f"/api/v1/admin/billing/statements/{statement_id}/reminder", headers=admin_headers)
    assert failed.status_code == 400
    assert "email" in failed.json()["detail"].lower()


def test_receipt_endpoint_creates_notification() -> None:
    _set_email_enabled(False)
    client = _build_client()
    admin_headers = _login(client, username="admin_a", condominium="Condo A")
    period_id = _create_period(client, admin_headers)
    generated = client.post(f"/api/v1/admin/billing/periods/{period_id}/generate", headers=admin_headers)
    statement_id = generated.json()["statements"][0]["id"]
    client.patch(
        f"/api/v1/admin/billing/statements/{statement_id}/payment-status",
        json={"payment_status": "paid", "note": "Paid"},
        headers=admin_headers,
    )

    receipt = client.post(f"/api/v1/admin/billing/statements/{statement_id}/receipt", headers=admin_headers)
    assert receipt.status_code == 200
    assert receipt.json()["delivery_status"] == "preview"

    detail = client.get(f"/api/v1/admin/billing/statements/{statement_id}", headers=admin_headers)
    assert any(n["notification_type"] == "receipt" for n in detail.json()["notifications"])


def test_multipart_upload_job_history_and_row_results_work() -> None:
    _set_email_enabled(False)
    client = _build_client()
    admin_headers = _login(client, username="admin_a", condominium="Condo A")
    admin_b_headers = _login(client, username="admin_b", condominium="Condo B")
    period_id = _create_period(client, admin_headers)
    generated = client.post(f"/api/v1/admin/billing/periods/{period_id}/generate", headers=admin_headers)
    statements = generated.json()["statements"]
    resident1 = next(s for s in statements if s["resident_username"] == "resident_a1")

    csv_text = (
        "payment_reference,statement_number,amount_eur,received_at,transaction_reference,method,note\n"
        f"{resident1['payment_reference']},,1.00,2026-06-19T10:00:00Z,MULTI-1,bank_transfer,Matched row\n"
        ",,oops,2026-06-19T11:00:00Z,MULTI-2,bank_transfer,Failed row\n"
        ",UNKNOWN,2.50,2026-06-19T12:00:00Z,MULTI-3,cash,Unmatched row\n"
        f"{resident1['payment_reference']},,1.25,2026-06-19T13:00:00Z,MULTI-1,bank_transfer,Duplicate row\n"
    )
    uploaded = client.post(
        "/api/v1/admin/billing/payments/import",
        files={"file": ("payments.csv", csv_text, "text/csv")},
        headers=admin_headers,
    )
    assert uploaded.status_code == 200
    payload = uploaded.json()
    assert payload["imported_count"] == 1
    assert payload["duplicate_count"] == 1
    assert payload["unmatched_count"] == 1
    assert payload["failed_count"] == 1
    assert payload["import_job_id"] > 0
    assert len(payload["rows"]) == 4

    jobs = client.get("/api/v1/admin/billing/payments/import-jobs", headers=admin_headers)
    assert jobs.status_code == 200
    assert jobs.json()[0]["id"] == payload["import_job_id"]
    assert jobs.json()[0]["rows_total"] == 4
    assert jobs.json()[0]["rows_processed"] == 4
    assert jobs.json()[0]["progress_percent"] == 100
    assert jobs.json()[0]["status"] == "completed"
    assert jobs.json()[0]["rows_matched"] == 1
    assert jobs.json()[0]["rows_unmatched"] == 1
    assert jobs.json()[0]["rows_duplicate"] == 1
    assert jobs.json()[0]["rows_failed"] == 1

    detail = client.get(f"/api/v1/admin/billing/payments/import-jobs/{payload['import_job_id']}", headers=admin_headers)
    assert detail.status_code == 200
    detail_payload = detail.json()
    assert len(detail_payload["rows"]) == 4
    statuses = [row["status"] for row in detail_payload["rows"]]
    assert statuses == ["matched", "failed", "unmatched", "duplicate"]
    failed_row = next(row for row in detail_payload["rows"] if row["status"] == "failed")
    assert "amount" in failed_row["error_message"].lower() or "required" in failed_row["error_message"].lower()
    unmatched_row = next(row for row in detail_payload["rows"] if row["status"] == "unmatched")
    assert unmatched_row["unmatched_payment_id"] is not None

    forbidden = client.get(f"/api/v1/admin/billing/payments/import-jobs/{payload['import_job_id']}", headers=admin_b_headers)
    assert forbidden.status_code == 404

    errors_csv = client.get(
        f"/api/v1/admin/billing/payments/import-jobs/{payload['import_job_id']}/errors.csv",
        headers=admin_headers,
    )
    assert errors_csv.status_code == 200
    body = errors_csv.content.decode("utf-8")
    assert "status" in body
    assert ",matched," not in body
    assert "failed" in body
    assert "duplicate" in body
    assert "unmatched" in body


def test_empty_multipart_file_rejected() -> None:
    client = _build_client()
    admin_headers = _login(client, username="admin_a", condominium="Condo A")
    uploaded = client.post(
        "/api/v1/admin/billing/payments/import",
        files={"file": ("payments.csv", b"", "text/csv")},
        headers=admin_headers,
    )
    assert uploaded.status_code == 400
    assert "empty" in uploaded.json()["detail"].lower()


def test_email_health_and_test_send_preview_and_validation_work() -> None:
    _set_email_enabled(False)
    client = _build_client()
    admin_headers = _login(client, username="admin_a", condominium="Condo A")

    health = client.get("/api/v1/admin/email/health", headers=admin_headers)
    assert health.status_code == 200
    assert health.json()["status"] == "disabled"

    invalid = client.post("/api/v1/admin/email/test-send", json={"recipient_email": "nope"}, headers=admin_headers)
    assert invalid.status_code == 422

    preview = client.post(
        "/api/v1/admin/email/test-send",
        json={"recipient_email": "ops@example.com"},
        headers=admin_headers,
    )
    assert preview.status_code == 200
    assert preview.json()["delivery_status"] == "preview"
    assert preview.json()["email_enabled"] is False


def test_csv_import_matches_fallback_duplicates_unmatched_and_received_date_filters() -> None:
    _set_email_enabled(False)
    client = _build_client()
    admin_headers = _login(client, username="admin_a", condominium="Condo A")
    period_id = _create_period(client, admin_headers)
    generated = client.post(f"/api/v1/admin/billing/periods/{period_id}/generate", headers=admin_headers)
    statements = generated.json()["statements"]
    resident1 = next(s for s in statements if s["resident_username"] == "resident_a1")
    resident2 = next(s for s in statements if s["resident_username"] == "resident_a2")

    csv_text = (
        "payment_reference,statement_number,amount_eur,received_at,transaction_reference,method,note\n"
        f"{resident1['payment_reference']},,1.50,2026-06-15T10:00:00Z,IMP-1,bank_transfer,By reference\n"
        f", {resident2['statement_number']},1.60,2026-06-16T11:00:00Z,IMP-2,cash,By statement number\n"
        f"{resident1['payment_reference']},,2.00,2026-06-17T12:00:00Z,IMP-1,bank_transfer,Duplicate tx\n"
        ",UNKNOWN,3.00,2026-06-18T09:30:00Z,IMP-3,other,Unmatched row\n"
    )
    imported = client.post(
        "/api/v1/admin/billing/payments/import.csv",
        data=csv_text,
        headers={**admin_headers, "Content-Type": "text/csv"},
    )
    assert imported.status_code == 200
    payload = imported.json()
    assert payload["imported_count"] == 2
    assert payload["duplicate_count"] == 1
    assert payload["unmatched_count"] == 1

    resident1_detail = client.get(f"/api/v1/admin/billing/statements/{resident1['id']}", headers=admin_headers)
    assert resident1_detail.status_code == 200
    assert resident1_detail.json()["amount_paid_eur"] == 1.5
    assert resident1_detail.json()["payment_status"] == "partially_paid"

    resident2_detail = client.get(f"/api/v1/admin/billing/statements/{resident2['id']}", headers=admin_headers)
    assert resident2_detail.status_code == 200
    assert resident2_detail.json()["amount_paid_eur"] == 1.6
    assert resident2_detail.json()["payment_status"] == "paid"

    reconciliation = client.get(
        "/api/v1/admin/billing/reconciliation",
        params={"received_from_date": "2026-06-15T00:00:00Z", "received_to_date": "2026-06-16T23:59:59Z"},
        headers=admin_headers,
    )
    assert reconciliation.status_code == 200
    rec = reconciliation.json()
    assert rec["total_received_eur"] == 3.1
    assert rec["unmatched_payments_count"] == 1
    assert rec["unmatched_payments_amount_eur"] == 3.0


def test_reconciliation_only_counts_active_unmatched_payments_after_match_and_ignore() -> None:
    _set_email_enabled(False)
    client = _build_client()
    admin_a_headers = _login(client, username="admin_a", condominium="Condo A")
    admin_b_headers = _login(client, username="admin_b", condominium="Condo B")
    period_id = _create_period(client, admin_a_headers)
    generated = client.post(f"/api/v1/admin/billing/periods/{period_id}/generate", headers=admin_a_headers)
    assert generated.status_code == 200
    statement_id = generated.json()["statements"][0]["id"]

    def import_unmatched_payment(*, transaction_reference: str, amount_eur: float, note: str) -> int:
        csv_text = (
            "payment_reference,statement_number,amount_eur,received_at,transaction_reference,method,note\n"
            f",UNKNOWN,{amount_eur:.2f},2026-06-18T09:30:00Z,{transaction_reference},bank_transfer,{note}\n"
        )
        imported = client.post(
            "/api/v1/admin/billing/payments/import.csv",
            content=csv_text,
            headers={**admin_a_headers, "Content-Type": "text/csv"},
        )
        assert imported.status_code == 200
        payload = imported.json()
        assert payload["imported_count"] == 0
        assert payload["duplicate_count"] == 0
        assert payload["unmatched_count"] == 1
        assert len(payload["unmatched_payments"]) == 1
        return int(payload["unmatched_payments"][0]["id"])

    def get_reconciliation(headers: dict[str, str]) -> dict[str, object]:
        response = client.get("/api/v1/admin/billing/reconciliation", headers=headers)
        assert response.status_code == 200
        return response.json()

    unmatched_to_match_id = import_unmatched_payment(
        transaction_reference="MATCH-IMP-1",
        amount_eur=3.00,
        note="Needs manual match",
    )

    rec = get_reconciliation(admin_a_headers)
    assert rec["unmatched_payments_count"] == 1
    assert rec["unmatched_payments_amount_eur"] == 3.0
    assert len(rec["unmatched_payments"]) == 1
    assert rec["unmatched_payments"][0]["status"] == "unmatched"

    other_tenant_rec = get_reconciliation(admin_b_headers)
    assert other_tenant_rec["unmatched_payments_count"] == 0
    assert other_tenant_rec["unmatched_payments_amount_eur"] == 0.0
    assert other_tenant_rec["unmatched_payments"] == []

    forbidden_match = client.post(
        f"/api/v1/admin/billing/unmatched-payments/{unmatched_to_match_id}/match",
        json={"statement_id": statement_id},
        headers=admin_b_headers,
    )
    assert forbidden_match.status_code == 404

    matched = client.post(
        f"/api/v1/admin/billing/unmatched-payments/{unmatched_to_match_id}/match",
        json={"statement_id": statement_id},
        headers=admin_a_headers,
    )
    assert matched.status_code == 200
    assert matched.json()["status"] == "matched"

    rec_after_match = get_reconciliation(admin_a_headers)
    assert rec_after_match["unmatched_payments_count"] == 0
    assert rec_after_match["unmatched_payments_amount_eur"] == 0.0
    assert rec_after_match["unmatched_payments"] == []

    other_tenant_rec_after_match = get_reconciliation(admin_b_headers)
    assert other_tenant_rec_after_match["unmatched_payments_count"] == 0
    assert other_tenant_rec_after_match["unmatched_payments_amount_eur"] == 0.0
    assert other_tenant_rec_after_match["unmatched_payments"] == []

    unmatched_to_ignore_id = import_unmatched_payment(
        transaction_reference="IGNORE-IMP-1",
        amount_eur=4.00,
        note="Needs manual ignore",
    )

    rec_before_ignore = get_reconciliation(admin_a_headers)
    assert rec_before_ignore["unmatched_payments_count"] == 1
    assert rec_before_ignore["unmatched_payments_amount_eur"] == 4.0
    assert len(rec_before_ignore["unmatched_payments"]) == 1
    assert rec_before_ignore["unmatched_payments"][0]["id"] == unmatched_to_ignore_id

    forbidden_ignore = client.patch(
        f"/api/v1/admin/billing/unmatched-payments/{unmatched_to_ignore_id}/ignore",
        json={"note": "cross-tenant"},
        headers=admin_b_headers,
    )
    assert forbidden_ignore.status_code == 404

    ignored = client.patch(
        f"/api/v1/admin/billing/unmatched-payments/{unmatched_to_ignore_id}/ignore",
        json={"note": "Not a valid payment"},
        headers=admin_a_headers,
    )
    assert ignored.status_code == 200
    assert ignored.json()["status"] == "ignored"

    rec_after_ignore = get_reconciliation(admin_a_headers)
    assert rec_after_ignore["unmatched_payments_count"] == 0
    assert rec_after_ignore["unmatched_payments_amount_eur"] == 0.0
    assert rec_after_ignore["unmatched_payments"] == []

    other_tenant_rec_after_ignore = get_reconciliation(admin_b_headers)
    assert other_tenant_rec_after_ignore["unmatched_payments_count"] == 0
    assert other_tenant_rec_after_ignore["unmatched_payments_amount_eur"] == 0.0
    assert other_tenant_rec_after_ignore["unmatched_payments"] == []


def test_retry_notification_respects_tenant_scope_and_preview_attachment_metadata_exists() -> None:
    _set_email_enabled(False)
    client = _build_client()
    admin_headers = _login(client, username="admin_a", condominium="Condo A")
    admin_b_headers = _login(client, username="admin_b", condominium="Condo B")
    period_id = _create_period(client, admin_headers)
    generated = client.post(f"/api/v1/admin/billing/periods/{period_id}/generate", headers=admin_headers)
    statement_id = generated.json()["statements"][0]["id"]

    reminder = client.post(f"/api/v1/admin/billing/statements/{statement_id}/reminder", headers=admin_headers)
    assert reminder.status_code == 200
    reminder_payload = reminder.json()
    assert reminder_payload["attachments"]
    assert reminder_payload["attachments"][0]["filename"].endswith(".pdf")
    notification_id = reminder_payload["notification_id"]

    forbidden = client.post(f"/api/v1/admin/billing/notifications/{notification_id}/retry", headers=admin_b_headers)
    assert forbidden.status_code == 404

    retried = client.post(f"/api/v1/admin/billing/notifications/{notification_id}/retry", headers=admin_headers)
    assert retried.status_code == 200
    assert retried.json()["status"] == "preview"
    assert retried.json()["retry_of_notification_id"] == notification_id


def test_statement_send_creates_statement_notification() -> None:
    _set_email_enabled(False)
    client = _build_client()
    admin_headers = _login(client, username="admin_a", condominium="Condo A")
    period_id = _create_period(client, admin_headers)
    generated = client.post(f"/api/v1/admin/billing/periods/{period_id}/generate", headers=admin_headers)
    statement_id = generated.json()["statements"][0]["id"]

    sent = client.post(f"/api/v1/admin/billing/statements/{statement_id}/send", headers=admin_headers)
    assert sent.status_code == 200
    assert sent.json()["delivery_status"] == "preview"
    assert sent.json()["attachments"]

    detail = client.get(f"/api/v1/admin/billing/statements/{statement_id}", headers=admin_headers)
    assert any(n["notification_type"] == "statement" for n in detail.json()["notifications"])


def test_reminder_candidates_and_run_respect_rules_and_repeat_window_and_tenant_isolation() -> None:
    _set_email_enabled(False)
    client = _build_client()
    admin_a_headers = _login(client, username="admin_a", condominium="Condo A")
    admin_b_headers = _login(client, username="admin_b", condominium="Condo B")
    period_id = _create_period(client, admin_a_headers)
    generated = client.post(f"/api/v1/admin/billing/periods/{period_id}/generate", headers=admin_a_headers)
    assert generated.status_code == 200
    closed = client.post(f"/api/v1/admin/billing/periods/{period_id}/close", headers=admin_a_headers)
    assert closed.status_code == 200

    updated = client.put(
        "/api/v1/admin/billing/reminders/rule",
        json={
            "enabled": True,
            "days_after_period_close": 0,
            "repeat_every_days": 30,
            "max_reminders": 5,
            "min_amount_due_eur": 0.0,
        },
        headers=admin_a_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["enabled"] is True

    candidates = client.get("/api/v1/admin/billing/reminders/candidates", headers=admin_a_headers)
    assert candidates.status_code == 200
    assert len(candidates.json()) > 0

    run1 = client.post("/api/v1/admin/billing/reminders/run", headers=admin_a_headers)
    assert run1.status_code == 200
    assert run1.json()["candidates_count"] == len(candidates.json())
    assert run1.json()["preview_count"] == len(candidates.json())

    run2 = client.post("/api/v1/admin/billing/reminders/run", headers=admin_a_headers)
    assert run2.status_code == 200
    assert run2.json()["preview_count"] == 0

    b_rule = client.get("/api/v1/admin/billing/reminders/rule", headers=admin_b_headers)
    assert b_rule.status_code == 200
    assert b_rule.json()["condominium_id"] != updated.json()["condominium_id"]

    b_candidates = client.get("/api/v1/admin/billing/reminders/candidates", headers=admin_b_headers)
    assert b_candidates.status_code == 200
    assert b_candidates.json() == []


def test_overpayment_does_not_create_negative_due_and_waive_sets_waived() -> None:
    client = _build_client()
    admin_a_headers = _login(client, username="admin_a", condominium="Condo A")
    period_id = _create_period(client, admin_a_headers)
    generated = client.post(f"/api/v1/admin/billing/periods/{period_id}/generate", headers=admin_a_headers)
    assert generated.status_code == 200
    resident2_statement_id = next(s["id"] for s in generated.json()["statements"] if s["resident_username"] == "resident_a2")

    overpay = client.post(
        f"/api/v1/admin/billing/statements/{resident2_statement_id}/payments",
        json={
            "amount_eur": 10.0,
            "method": "other",
            "transaction_reference": "TX-OVER",
            "note": "Overpay",
            "received_at": "2026-06-12T10:00:00Z",
        },
        headers=admin_a_headers,
    )
    assert overpay.status_code == 201

    detail_overpay = client.get(f"/api/v1/admin/billing/statements/{resident2_statement_id}", headers=admin_a_headers)
    assert detail_overpay.status_code == 200
    assert detail_overpay.json()["payment_status"] == "paid"
    assert detail_overpay.json()["amount_due_eur"] == 0.0

    waived = client.patch(
        f"/api/v1/admin/billing/statements/{resident2_statement_id}/waive",
        json={"note": "Waived by admin"},
        headers=admin_a_headers,
    )
    assert waived.status_code == 200
    assert waived.json()["payment_status"] == "waived"
    assert waived.json()["amount_due_eur"] == 0.0
