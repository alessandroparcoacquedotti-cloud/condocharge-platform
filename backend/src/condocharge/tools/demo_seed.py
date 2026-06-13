from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from condocharge.app.services.billing_service import BillingService
from condocharge.core.security import hash_password
from condocharge.db.session import SessionLocal
from condocharge.models.billing import BillingPeriod, ResidentBillingStatement
from condocharge.models.charging import ChargingSession, ChargingStation, RfidUser
from condocharge.models.tenancy import AppUser, AppUserRole, Condominium


DEMO_CONDOMINIUM_NAME = "Portfolio Demo Condominium"
DEMO_ADMIN_USERNAME = "demo_admin"
DEMO_ADMIN_PASSWORD = "demo_admin"


def _month_bounds(reference: datetime) -> tuple[datetime, datetime]:
    this_month_start = reference.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    prev_month_end = this_month_start - timedelta(seconds=1)
    prev_month_start = prev_month_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return prev_month_start, this_month_start


def _get_or_create_condominium(db, *, name: str) -> Condominium:
    condo = db.scalar(select(Condominium).where(Condominium.name == name))
    if condo is not None:
        return condo
    condo = Condominium(name=name, energy_price_eur_per_kwh=Decimal("0.35"))
    db.add(condo)
    db.commit()
    db.refresh(condo)
    return condo


def _get_or_create_user(
    db,
    *,
    condominium_id: int,
    username: str,
    password: str,
    role: str,
    email: str | None,
) -> AppUser:
    user = db.scalar(
        select(AppUser).where(AppUser.condominium_id == condominium_id).where(AppUser.username == username)
    )
    if user is not None:
        return user
    user = AppUser(
        condominium_id=condominium_id,
        username=username,
        email=email,
        password_hash=hash_password(password),
        role=role,
        is_active=1,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _get_or_create_station(db, *, condominium_id: int, host: str, name: str) -> ChargingStation:
    station = db.scalar(select(ChargingStation).where(ChargingStation.host == host))
    if station is not None:
        return station
    station = ChargingStation(
        condominium_id=condominium_id,
        host=host,
        vendor="legrand_greenup",
        name=name,
        status="online",
        status_source="demo_seed",
        last_sync_at=datetime.now(tz=timezone.utc),
    )
    db.add(station)
    db.commit()
    db.refresh(station)
    return station


def _get_or_create_rfid(db, *, condominium_id: int, app_user_id: int, rfid_id: str, name: str) -> RfidUser:
    rfid = db.scalar(select(RfidUser).where(RfidUser.rfid_id == rfid_id))
    if rfid is not None:
        return rfid
    rfid = RfidUser(
        condominium_id=condominium_id,
        app_user_id=app_user_id,
        rfid_id=rfid_id,
        name=name,
    )
    db.add(rfid)
    db.commit()
    db.refresh(rfid)
    return rfid


def _get_or_create_session(
    db,
    *,
    condominium_id: int,
    station_id: int,
    rfid_user_id: int,
    source_key: str,
    start_time: datetime,
    end_time: datetime,
    energy_wh: int,
) -> ChargingSession:
    existing = db.scalar(select(ChargingSession).where(ChargingSession.source_key == source_key))
    if existing is not None:
        return existing
    total_minutes = int((end_time - start_time).total_seconds() // 60)
    charging_minutes = max(total_minutes - 10, 1)
    session = ChargingSession(
        condominium_id=condominium_id,
        station_id=station_id,
        rfid_user_id=rfid_user_id,
        source_key=source_key,
        start_time=start_time,
        end_time=end_time,
        energy_wh=energy_wh,
        total_minutes=total_minutes,
        charging_minutes=charging_minutes,
        idle_minutes=max(total_minutes - charging_minutes, 0),
        plug_type="type2",
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def seed_demo_data(*, condominium_name: str) -> None:
    now = datetime.now(tz=timezone.utc)
    period_start, period_end = _month_bounds(now)
    period_name = f"Demo Billing {period_start.strftime('%Y-%m')}"

    with SessionLocal() as db:
        service = BillingService(db=db)
        condo = _get_or_create_condominium(db, name=condominium_name)

        demo_admin = _get_or_create_user(
            db,
            condominium_id=condo.id,
            username=DEMO_ADMIN_USERNAME,
            password=DEMO_ADMIN_PASSWORD,
            role=AppUserRole.ADMIN,
            email="demo_admin@condocharge.local",
        )
        resident_1 = _get_or_create_user(
            db,
            condominium_id=condo.id,
            username="demo_resident_1",
            password="resident1",
            role=AppUserRole.RESIDENT,
            email="resident1@example.com",
        )
        resident_2 = _get_or_create_user(
            db,
            condominium_id=condo.id,
            username="demo_resident_2",
            password="resident2",
            role=AppUserRole.RESIDENT,
            email="resident2@example.com",
        )

        station_a = _get_or_create_station(
            db,
            condominium_id=condo.id,
            host="demo-station-1.local",
            name="Demo Station A",
        )
        station_b = _get_or_create_station(
            db,
            condominium_id=condo.id,
            host="demo-station-2.local",
            name="Demo Station B",
        )

        rfid_1 = _get_or_create_rfid(
            db,
            condominium_id=condo.id,
            app_user_id=resident_1.id,
            rfid_id="DEMO-RFID-001",
            name="Resident 1 RFID",
        )
        rfid_2 = _get_or_create_rfid(
            db,
            condominium_id=condo.id,
            app_user_id=resident_2.id,
            rfid_id="DEMO-RFID-002",
            name="Resident 2 RFID",
        )

        _get_or_create_session(
            db,
            condominium_id=condo.id,
            station_id=station_a.id,
            rfid_user_id=rfid_1.id,
            source_key="demo-session-r1-1",
            start_time=period_start + timedelta(days=3, hours=18),
            end_time=period_start + timedelta(days=3, hours=20),
            energy_wh=14600,
        )
        _get_or_create_session(
            db,
            condominium_id=condo.id,
            station_id=station_a.id,
            rfid_user_id=rfid_1.id,
            source_key="demo-session-r1-2",
            start_time=period_start + timedelta(days=10, hours=19),
            end_time=period_start + timedelta(days=10, hours=21, minutes=15),
            energy_wh=17300,
        )
        _get_or_create_session(
            db,
            condominium_id=condo.id,
            station_id=station_b.id,
            rfid_user_id=rfid_2.id,
            source_key="demo-session-r2-1",
            start_time=period_start + timedelta(days=6, hours=17, minutes=30),
            end_time=period_start + timedelta(days=6, hours=19, minutes=10),
            energy_wh=9200,
        )
        _get_or_create_session(
            db,
            condominium_id=condo.id,
            station_id=station_b.id,
            rfid_user_id=rfid_2.id,
            source_key="demo-session-r2-2",
            start_time=period_start + timedelta(days=14, hours=18),
            end_time=period_start + timedelta(days=14, hours=19, minutes=45),
            energy_wh=11100,
        )

        period = db.scalar(
            select(BillingPeriod)
            .where(BillingPeriod.condominium_id == condo.id)
            .where(BillingPeriod.name == period_name)
        )
        if period is None:
            period = service.create_period(
                condominium=condo,
                name=period_name,
                period_start=period_start,
                period_end=period_end,
            )

        period = service.generate_period(condominium=condo, period=period)
        if period.status != "closed":
            period = service.close_period(condominium=condo, period=period)

        statements = db.scalars(
            select(ResidentBillingStatement).where(ResidentBillingStatement.billing_period_id == period.id)
        ).all()
        statements_by_user = {statement.resident_app_user_id: statement for statement in statements}

        partial_statement = statements_by_user.get(resident_1.id)
        unpaid_statement = statements_by_user.get(resident_2.id)
        if partial_statement is not None:
            existing_partial = any(
                payment.transaction_reference == "DEMO-PARTIAL-001" for payment in partial_statement.payments
            )
            if not existing_partial:
                partial_amount = (Decimal(str(partial_statement.amount_eur)) / Decimal("2")).quantize(Decimal("0.01"))
                service.add_payment(
                    condominium_id=condo.id,
                    statement_id=partial_statement.id,
                    created_by_app_user_id=demo_admin.id,
                    amount_eur=partial_amount,
                    method="bank_transfer",
                    transaction_reference="DEMO-PARTIAL-001",
                    note="Demo partial payment",
                    received_at=period_end - timedelta(days=2),
                )

        print("Demo seed complete")
        print(f"Condominium: {condo.name}")
        print(f"Demo admin: {DEMO_ADMIN_USERNAME} / {DEMO_ADMIN_PASSWORD}")
        if partial_statement is not None:
            refreshed_partial = service.get_statement_for_admin(condominium_id=condo.id, statement_id=partial_statement.id)
            print(
                f"Partial payment statement: {refreshed_partial.statement_number} "
                f"status={refreshed_partial.payment_status} due={float(refreshed_partial.amount_due_eur):.2f}"
            )
        if unpaid_statement is not None:
            refreshed_unpaid = service.get_statement_for_admin(condominium_id=condo.id, statement_id=unpaid_statement.id)
            print(
                f"Unpaid statement: {refreshed_unpaid.statement_number} "
                f"status={refreshed_unpaid.payment_status} due={float(refreshed_unpaid.amount_due_eur):.2f}"
            )
        print("This script is for demo/development data only and does not delete existing real data.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed CondoCharge demo/dev data without deleting existing data.")
    parser.add_argument(
        "--condominium-name",
        default=DEMO_CONDOMINIUM_NAME,
        help="Name of the demo condominium to create or reuse.",
    )
    args = parser.parse_args()
    seed_demo_data(condominium_name=args.condominium_name)


if __name__ == "__main__":
    main()
