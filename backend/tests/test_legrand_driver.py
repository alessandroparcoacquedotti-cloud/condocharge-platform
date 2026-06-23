from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import parse_qs

import httpx

from condocharge.app.integrations.base.models import ConnectorStatus
from condocharge.app.integrations.legrand.driver import LegrandGreenUpDriver

LOGIN_PAGE = "<html><body><div class='connexion-box'>login</div></body></html>"

TABLEAU_RIGHT_HTML = (
    "\r\n<!DOCTYPE html >\r\n"
    "<div class='text-center'>"
    "<img class='borne-img js-gif' src='assets/images/animate/battery_1-ready_icon.svg'>"
    "<p class='t-size-medium'>Pronto per la ricarica</p>"
    "<p class='text-blue-grey-light t-size-small'>Carico diretto</p>"
    "</div>"
    "<p class='t-size-medium'>Dati Elettricità</p>"
    "<div class='info-row info-row-border row align-middle collapse'>"
    "<div class='columns small-6 text-blue-grey-light'><p>Corrente massima di caricamento: </p></div>"
    "<div class='columns small-6 text-right'><p>32A</p></div>"
    "</div>"
    "<div class='info-row info-row-border row align-middle collapse'>"
    "<div class='columns small-6 text-blue-grey-light'><p>Corrente ricarica istantanea: </p></div>"
    "<div class='columns small-6 text-right'><p>0.00A</p></div>"
    "</div>"
    "<div class='info-row info-row-border row align-middle collapse'>"
    "<div class='columns small-6 text-blue-grey-light'><p>Potenza istantanea :</p></div>"
    "<div class='columns small-6 text-right'><p>0.00kVA</p></div>"
    "</div>"
)

RFID_RIGHT_HTML = (
    "\r\n<!DOCTYPE html >\r\n"
    "<div class='text-center'>"
    "<img class='borne-img js-gif' src='assets/images/animate/battery_1-ready_icon.svg'>"
    "<p class='t-size-medium'>Pronto per la ricarica</p>"
    "<p class='text-blue-grey-light t-size-small'>Carico diretto</p>"
    "</div>"
    "<p class='t-size-medium'>RFID</p>"
    "<div class='info-row info-row-border row align-middle collapse'>"
    "<div class='columns small-6 text-blue-grey-light'><p>Attivazione RFID:</p></div>"
    "<div class='columns small-6 text-right'><p>Attivo</p></div>"
    "</div>"
    "<div class='info-row info-row-border row align-middle collapse'>"
    "<div class='columns small-6 text-blue-grey-light'><p>Programmazione badge:</p></div>"
    "<div class='columns small-6 text-right'><p>Modo utilizzo</p></div>"
    "</div>"
)

ITALIAN_CSV_SAMPLE = (
    "Data e Ora sessione d’inizio;Tempo totale in min;Tempo senza ricarica in min;"
    "Tempo di ricarica in min;Energia in Wh;Data e Ora sessione finale;Tipo di spina;"
    "Id (se si usa RFID);Nome (se si usa RFID)\n"
    "23/06/2026 08:42;267;144;123;6333,58;23/06/2026 13:09;T2S;8AC7E266;Mario Rossi\n"
).encode("utf-8-sig")

FRENCH_CSV_SAMPLE = (
    "Date et heure de début de la session;Temps total en min;Temps sans charge en min;"
    "Temps de charge en min;Energie en Wh;Date et heure de fin de la session;Type de fiche;"
    "Id (si RFID activé);nom (si RFID activé)\n"
    "23/06/2026 08:42;267;144;123;6333,58;23/06/2026 13:09;T2S;8AC7E266;Daniela Battistini E18\n"
).encode("utf-8-sig")

MIXED_LOCALE_CSV_SAMPLE = (
    "Date et heure de début de la session;Tempo totale in min;Temps sans charge en min;"
    "Tempo di ricarica in min;Energie en Wh;Date et heure de fin de la session;Type de fiche;"
    "Id (si RFID activé);Nome (se si usa RFID)\n"
    "23/06/2026 08:42;267;144;123;6333,58;23/06/2026 13:09;T2S;8AC7E266;Mixed Header User\n"
).encode("utf-8-sig")


def _make_transport(state: dict[str, Any]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        query = parse_qs(request.url.query.decode() if isinstance(request.url.query, bytes) else request.url.query)

        cookie = request.headers.get("cookie", "")
        authed = "JSESSIONID=" in cookie

        if path == "/":
            return httpx.Response(
                200,
                headers={"Set-Cookie": "JSESSIONID=bootstrap; Path=/; HttpOnly"},
                text="ok",
                request=request,
            )

        if path == "/LoginTdB" and request.method == "POST":
            state["login_calls"] += 1
            body = request.content.decode()
            assert "user-id=admin" in body
            assert "user-pass=admin" in body
            assert "timeZone=" in body
            assert "year=" in body
            return httpx.Response(
                200,
                headers={"Set-Cookie": "JSESSIONID=abc123; Path=/myfirstwebproject; HttpOnly"},
                text="<html><body>dashboard</body></html>",
                request=request,
            )

        if path == "/Update_state.jsp" and request.method == "GET":
            if not authed:
                return httpx.Response(200, text=LOGIN_PAGE, request=request)
            side = (query.get("side") or [""])[0]
            kind = (query.get("type") or [""])[0]
            if side == "right" and kind == "TableauDeBord":
                return httpx.Response(200, headers={"Content-Type": "text/html;charset=utf-8"}, text=TABLEAU_RIGHT_HTML, request=request)
            if side == "right" and kind == "RFID":
                return httpx.Response(200, headers={"Content-Type": "text/html;charset=utf-8"}, text=RFID_RIGHT_HTML, request=request)
            return httpx.Response(404, text="not found", request=request)

        if path == "/Download" and request.method == "POST":
            if not authed:
                return httpx.Response(200, text=LOGIN_PAGE, request=request)
            side = (query.get("side") or [""])[0]
            kind = (query.get("type") or [""])[0]
            if side == "right" and kind == "chargeSession":
                csv_bytes = (
                    b"Data inizio;Data fine;Energia (Wh);Minuti totali;Minuti carica;Minuti attesa;Tipo presa;ID RFID;Nome RFID\n"
                    b"09/06/2026 12:00:00;09/06/2026 12:30:00;3500;30;25;5;Type2;1234;Mario\n"
                )
                return httpx.Response(
                    200,
                    headers={"Content-Type": "text/csv"},
                    content=csv_bytes,
                    request=request,
                )
            return httpx.Response(404, text="not found", request=request)

        return httpx.Response(404, text="not found", request=request)

    return httpx.MockTransport(handler)


def test_login_session_persistence_and_status_parsing() -> None:
    state: dict[str, Any] = {"login_calls": 0}
    transport = _make_transport(state)
    driver = LegrandGreenUpDriver(transport=transport, base_retry_delay_s=0.0, sleep=lambda _: None)

    driver.login("192.168.1.200", "admin", "admin")
    s1 = driver.get_station_status("192.168.1.200")
    s2 = driver.get_station_status("192.168.1.200")

    assert state["login_calls"] == 1
    assert str(s1.connector_status) == "available"
    assert s1.max_charging_current_a == 32.0
    assert s1.instantaneous_power_kva == 0.0
    assert s2.state_text == "Pronto per la ricarica"


def test_rfid_status_parsing() -> None:
    state: dict[str, Any] = {"login_calls": 0}
    driver = LegrandGreenUpDriver(transport=_make_transport(state), base_retry_delay_s=0.0, sleep=lambda _: None)

    driver.login("192.168.1.200", "admin", "admin")
    r = driver.get_rfid_status("192.168.1.200")

    assert r.station_state == "Pronto per la ricarica"
    assert r.rfid_enabled is True
    assert r.badge_programming_mode == "Modo utilizzo"


def test_charge_session_csv_parsing_and_sync() -> None:
    state: dict[str, Any] = {"login_calls": 0}
    driver = LegrandGreenUpDriver(transport=_make_transport(state), base_retry_delay_s=0.0, sleep=lambda _: None)

    driver.login("192.168.1.200", "admin", "admin")
    sessions = driver.sync_charge_sessions("192.168.1.200")

    assert len(sessions) == 1
    s = sessions[0]
    assert s.energy_wh == 3500
    assert s.total_minutes == 30
    assert s.charging_minutes == 25
    assert s.idle_minutes == 5
    assert s.plug_type == "Type2"
    assert s.rfid_id == "1234"
    assert s.rfid_name == "Mario"
    assert s.start_time == datetime.strptime("09/06/2026 12:00:00", "%d/%m/%Y %H:%M:%S")


def test_parse_charge_session_csv_supports_italian_headers() -> None:
    driver = LegrandGreenUpDriver(base_retry_delay_s=0.0, sleep=lambda _: None)

    sessions = driver.parse_charge_session_csv(ITALIAN_CSV_SAMPLE)

    assert len(sessions) == 1
    session = sessions[0]
    assert session.energy_wh == 6334
    assert session.total_minutes == 267
    assert session.charging_minutes == 123
    assert session.idle_minutes == 144
    assert session.plug_type == "T2S"
    assert session.rfid_id == "8AC7E266"
    assert session.rfid_name == "Mario Rossi"


def test_parse_charge_session_csv_supports_french_headers() -> None:
    driver = LegrandGreenUpDriver(base_retry_delay_s=0.0, sleep=lambda _: None)

    sessions = driver.parse_charge_session_csv(FRENCH_CSV_SAMPLE)

    assert len(sessions) == 1
    session = sessions[0]
    assert session.energy_wh == 6334
    assert session.total_minutes == 267
    assert session.charging_minutes == 123
    assert session.idle_minutes == 144
    assert session.plug_type == "T2S"
    assert session.rfid_id == "8AC7E266"
    assert session.rfid_name == "Daniela Battistini E18"


def test_parse_charge_session_csv_supports_mixed_locale_headers() -> None:
    driver = LegrandGreenUpDriver(base_retry_delay_s=0.0, sleep=lambda _: None)

    sessions = driver.parse_charge_session_csv(MIXED_LOCALE_CSV_SAMPLE)

    assert len(sessions) == 1
    session = sessions[0]
    assert session.energy_wh == 6334
    assert session.total_minutes == 267
    assert session.charging_minutes == 123
    assert session.idle_minutes == 144
    assert session.plug_type == "T2S"
    assert session.rfid_id == "8AC7E266"
    assert session.rfid_name == "Mixed Header User"


def test_existing_station_200_csv_sample_remains_valid() -> None:
    driver = LegrandGreenUpDriver(base_retry_delay_s=0.0, sleep=lambda _: None)

    sessions = driver.parse_charge_session_csv(ITALIAN_CSV_SAMPLE)

    assert len(sessions) == 1


def test_existing_station_201_csv_sample_becomes_valid() -> None:
    driver = LegrandGreenUpDriver(base_retry_delay_s=0.0, sleep=lambda _: None)

    sessions = driver.parse_charge_session_csv(FRENCH_CSV_SAMPLE)

    assert len(sessions) == 1


def test_retry_on_transient_timeout() -> None:
    calls: dict[str, int] = {"status_calls": 0, "login_calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(200, headers={"Set-Cookie": "JSESSIONID=bootstrap; Path=/; HttpOnly"}, request=request)
        if request.url.path == "/LoginTdB":
            calls["login_calls"] += 1
            return httpx.Response(
                200,
                headers={"Set-Cookie": "JSESSIONID=abc123; Path=/myfirstwebproject; HttpOnly"},
                text="<html><body>dashboard</body></html>",
                request=request,
            )
        if request.url.path == "/Update_state.jsp":
            calls["status_calls"] += 1
            if calls["status_calls"] == 1:
                raise httpx.ConnectTimeout("timeout", request=request)
            return httpx.Response(200, text=TABLEAU_RIGHT_HTML, request=request)
        return httpx.Response(404, text="not found", request=request)

    driver = LegrandGreenUpDriver(
        transport=httpx.MockTransport(handler),
        max_retries=2,
        base_retry_delay_s=0.0,
        sleep=lambda _: None,
    )
    driver.login("192.168.1.200", "admin", "admin")
    status = driver.get_station_status("192.168.1.200")
    assert str(status.connector_status) == "available"
    assert calls["status_calls"] == 2


def test_infer_connector_status_maps_french_completed_charge_to_occupied() -> None:
    driver = LegrandGreenUpDriver(base_retry_delay_s=0.0, sleep=lambda _: None)

    status = driver._infer_connector_status(
        "T2S charge terminée",
        "Charge immédiate",
        "<html></html>",
    )

    assert status == ConnectorStatus.OCCUPIED


def test_infer_connector_status_maps_accentless_french_completed_charge_to_occupied() -> None:
    driver = LegrandGreenUpDriver(base_retry_delay_s=0.0, sleep=lambda _: None)

    status = driver._infer_connector_status(
        "T2S charge terminee",
        "Charge immediate",
        "<html></html>",
    )

    assert status == ConnectorStatus.OCCUPIED
