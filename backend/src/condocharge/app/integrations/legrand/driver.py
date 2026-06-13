from __future__ import annotations

import csv
import random
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Final
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel

from condocharge.app.integrations.base.driver import StationDriver
from condocharge.app.integrations.base.errors import IntegrationError, StationUnreachableError
from condocharge.app.integrations.base.models import (
    ConnectorStatus,
    ConnectorStatusSnapshot,
    StationAvailability,
    StationStatusSnapshot,
    StationTarget,
    StationTelemetryPoint,
    StationVendor,
)


class LegrandGreenUpError(IntegrationError):
    pass


class LegrandGreenUpAuthenticationError(LegrandGreenUpError):
    pass


class LegrandGreenUpProtocolError(LegrandGreenUpError):
    pass


class ChargingSession(BaseModel):
    start_time: datetime
    end_time: datetime
    energy_wh: int
    total_minutes: int
    charging_minutes: int
    idle_minutes: int
    plug_type: str | None = None
    rfid_id: str | None = None
    rfid_name: str | None = None


class LegrandGreenUpStationStatus(BaseModel):
    connector_status: ConnectorStatus = ConnectorStatus.UNKNOWN
    state_text: str | None = None
    mode_text: str | None = None

    max_charging_current_a: float | None = None
    cable_max_current_a: float | None = None
    requested_current_a: float | None = None
    instantaneous_current_a: float | None = None
    instantaneous_power_kva: float | None = None


class LegrandGreenUpRfidStatus(BaseModel):
    station_state: str | None = None
    rfid_enabled: bool | None = None
    badge_programming_mode: str | None = None


@dataclass(frozen=True)
class _Credentials:
    username: str
    password: str


def _js_timezone_offset_minutes(now: datetime | None = None) -> int:
    base = now if now is not None else datetime.now(tz=timezone.utc)
    local_now = base.astimezone(ZoneInfo("Europe/Rome"))
    offset = local_now.utcoffset()
    if offset is None:
        return 0
    return int(-(offset.total_seconds() // 60))


_FLOAT_RE: Final[re.Pattern[str]] = re.compile(r"[-+]?\d+(?:[.,]\d+)?")


def _parse_float(text: str) -> float | None:
    m = _FLOAT_RE.search(text.replace("\xa0", " "))
    if not m:
        return None
    return float(m.group(0).replace(",", "."))


def _parse_int(text: str) -> int | None:
    value = _parse_float(text)
    if value is None:
        return None
    return int(round(value))


def _normalize_label(label: str) -> str:
    label = label.strip().lower().replace("\xa0", " ")
    label = re.sub(r"[\s:]+", " ", label)
    return label


def _looks_like_login_page(html: str) -> bool:
    s = html.lower()
    return "connexion-box" in s or "content-login" in s or "js-login" in s


def _parse_datetime(value: str) -> datetime | None:
    v = value.strip()
    if not v:
        return None
    if "t" in v and any(x in v for x in ["+", "z"]):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            pass
    for fmt in (
        "%d/%m/%Y %H:%M:%S%z",
        "%d/%m/%Y %H:%M%z",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(v, fmt)
        except ValueError:
            continue
    return None


def _parse_duration_minutes(value: str) -> int | None:
    v = value.strip()
    if not v:
        return None
    if ":" in v:
        parts = [p.strip() for p in v.split(":")]
        if len(parts) == 2:
            h = _parse_int(parts[0])
            m = _parse_int(parts[1])
            if h is None or m is None:
                return None
            return h * 60 + m
        if len(parts) == 3:
            h = _parse_int(parts[0])
            m = _parse_int(parts[1])
            s = _parse_int(parts[2])
            if h is None or m is None or s is None:
                return None
            return h * 60 + m + (1 if s >= 30 else 0)
    return _parse_int(v)


def _sniff_csv_dialect(text: str) -> csv.Dialect:
    try:
        return csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except Exception:
        return csv.get_dialect("excel")


class LegrandGreenUpDriver:
    vendor = StationVendor.LEGRAND_GREENUP

    def __init__(
        self,
        *,
        timeout: httpx.Timeout | None = None,
        max_retries: int = 3,
        base_retry_delay_s: float = 0.2,
        max_retry_delay_s: float = 2.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._timeout = timeout or httpx.Timeout(connect=3.0, read=6.0, write=6.0, pool=6.0)
        self._max_retries = max_retries
        self._base_retry_delay_s = base_retry_delay_s
        self._max_retry_delay_s = max_retry_delay_s
        self._transport = transport
        self._sleep = sleep

        self._clients: dict[str, httpx.Client] = {}
        self._credentials: dict[str, _Credentials] = {}

    def supports(self, target: StationTarget) -> bool:
        return target.vendor == StationVendor.LEGRAND_GREENUP

    def get_status(self, target: StationTarget) -> StationStatusSnapshot:
        observed_at = datetime.now(tz=timezone.utc)
        status = self.get_station_status(target.host)
        availability = StationAvailability.ONLINE
        connectors = [
            ConnectorStatusSnapshot(connector_id="right", status=status.connector_status, last_seen_at=observed_at)
        ]
        return StationStatusSnapshot(
            station_id=target.station_id,
            availability=availability,
            identity=None,
            connectors=connectors,
            observed_at=observed_at,
        )

    def get_telemetry(self, target: StationTarget) -> Sequence[StationTelemetryPoint]:
        observed_at = datetime.now(tz=timezone.utc)
        status = self.get_station_status(target.host)
        power_kw = status.instantaneous_power_kva
        return [
            StationTelemetryPoint(
                station_id=target.station_id,
                connector_id="right",
                observed_at=observed_at,
                power_kw=power_kw,
                current_a=status.instantaneous_current_a,
            )
        ]

    def close(self) -> None:
        for client in self._clients.values():
            client.close()
        self._clients.clear()

    def login(self, host: str, username: str, password: str) -> None:
        base_url = self._base_url(host)
        client = self._client_for_host(host)
        self._credentials[host] = _Credentials(username=username, password=password)

        self._request_with_retries(client, "GET", f"{base_url}/")

        now_utc = datetime.now(tz=timezone.utc)
        data = {
            "timeZone": str(_js_timezone_offset_minutes()),
            "year": str(now_utc.year),
            "month": str(now_utc.month),
            "day": str(now_utc.day),
            "hour": str(now_utc.hour),
            "minute": str(now_utc.minute),
            "second": str(now_utc.second),
            "user-id": username,
            "user-pass": password,
        }

        response = self._request_with_retries(client, "POST", f"{base_url}/LoginTdB", data=data)
        html = response.text
        if _looks_like_login_page(html):
            raise LegrandGreenUpAuthenticationError("Login failed (received login page again)")

        if not self._has_jsessionid(client):
            raise LegrandGreenUpProtocolError("Login succeeded but JSESSIONID cookie was not set")

    def get_station_status(self, host: str) -> LegrandGreenUpStationStatus:
        client = self._client_for_host(host)
        self._ensure_logged_in(host, client)

        url = f"{self._base_url(host)}/Update_state.jsp?{urlencode({'side': 'right', 'type': 'TableauDeBord'})}"
        response = self._request_with_retries(client, "GET", url)
        html = response.text
        if _looks_like_login_page(html):
            self._reauthenticate(host, client)
            response = self._request_with_retries(client, "GET", url)
            html = response.text
        return self._parse_station_status_html(html)

    def get_rfid_status(self, host: str) -> LegrandGreenUpRfidStatus:
        client = self._client_for_host(host)
        self._ensure_logged_in(host, client)

        url = f"{self._base_url(host)}/Update_state.jsp?{urlencode({'side': 'right', 'type': 'RFID'})}"
        response = self._request_with_retries(client, "GET", url)
        html = response.text
        if _looks_like_login_page(html):
            self._reauthenticate(host, client)
            response = self._request_with_retries(client, "GET", url)
            html = response.text
        return self._parse_rfid_status_html(html)

    def download_charge_sessions(self, host: str) -> bytes:
        client = self._client_for_host(host)
        self._ensure_logged_in(host, client)

        url = f"{self._base_url(host)}/Download?{urlencode({'side': 'right', 'type': 'chargeSession'})}"
        response = self._request_with_retries(
            client,
            "POST",
            url,
            headers={"Accept": "text/csv,*/*;q=0.9"},
        )
        content_type = response.headers.get("Content-Type", "")
        if "text/csv" not in content_type.lower():
            if _looks_like_login_page(response.text):
                raise LegrandGreenUpAuthenticationError("Not authenticated for CSV download")
        return response.content

    def parse_charge_session_csv(self, csv_content: bytes) -> list[ChargingSession]:
        if not csv_content:
            return []

        text: str
        try:
            text = csv_content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = csv_content.decode("iso-8859-1")

        text = text.replace("\r\n", "\n").replace("\r", "\n")
        dialect = _sniff_csv_dialect(text)
        reader = csv.DictReader(text.splitlines(), dialect=dialect)

        if reader.fieldnames is None:
            raise LegrandGreenUpProtocolError("CSV has no header row")

        header_map = {self._normalize_csv_header(h): h for h in reader.fieldnames if h is not None}
        resolved = self._resolve_charge_session_headers(header_map.keys())

        sessions: list[ChargingSession] = []
        for idx, row in enumerate(reader, start=2):
            raw = {k: (v.strip() if isinstance(v, str) else v) for k, v in row.items() if k is not None}
            try:
                sessions.append(self._row_to_charging_session(raw, resolved))
            except Exception as e:
                raise LegrandGreenUpProtocolError(f"Failed parsing CSV row {idx}: {e}") from e
        return sessions

    def sync_charge_sessions(self, host: str) -> list[ChargingSession]:
        return self.parse_charge_session_csv(self.download_charge_sessions(host))

    def _client_for_host(self, host: str) -> httpx.Client:
        client = self._clients.get(host)
        if client is not None:
            return client
        base_url = self._base_url(host)
        client = httpx.Client(
            base_url=base_url,
            follow_redirects=True,
            timeout=self._timeout,
            headers={"User-Agent": "CondoCharge-LegrandGreenUpDriver/1.0"},
            transport=self._transport,
        )
        self._clients[host] = client
        return client

    def _base_url(self, host: str) -> str:
        if host.startswith("http://") or host.startswith("https://"):
            return host.rstrip("/")
        return f"http://{host}".rstrip("/")

    def _retry_delay(self, attempt: int) -> float:
        base = min(self._max_retry_delay_s, self._base_retry_delay_s * (2**attempt))
        return base * (0.75 + (random.random() * 0.5))

    def _request_with_retries(
        self,
        client: httpx.Client,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
    ) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = client.request(method, url, headers=headers, data=data)
                if response.status_code >= 500:
                    last_exc = LegrandGreenUpProtocolError(f"Server error {response.status_code}")
                    if attempt < self._max_retries:
                        self._sleep(self._retry_delay(attempt))
                        continue
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as e:
                if e.response.status_code >= 500 and attempt < self._max_retries:
                    last_exc = e
                    self._sleep(self._retry_delay(attempt))
                    continue
                raise LegrandGreenUpProtocolError(
                    f"HTTP {e.response.status_code} for {method} {url}"
                ) from e
            except httpx.RequestError as e:
                last_exc = e
                if attempt < self._max_retries:
                    self._sleep(self._retry_delay(attempt))
                    continue
                raise StationUnreachableError(f"Failed request to {url}: {e}") from e
        raise LegrandGreenUpProtocolError(f"Request failed: {last_exc}")

    def _has_jsessionid(self, client: httpx.Client) -> bool:
        return any(cookie.name == "JSESSIONID" for cookie in client.cookies.jar)

    def _ensure_logged_in(self, host: str, client: httpx.Client) -> None:
        if self._has_jsessionid(client):
            return
        self._reauthenticate(host, client)

    def _reauthenticate(self, host: str, client: httpx.Client) -> None:
        creds = self._credentials.get(host)
        if creds is None:
            raise LegrandGreenUpAuthenticationError(f"No stored credentials for host {host}")
        self.login(host, creds.username, creds.password)

    def _parse_station_status_html(self, html: str) -> LegrandGreenUpStationStatus:
        soup = BeautifulSoup(html, "html.parser")
        state_text = None
        mode_text = None

        state_p = soup.select_one("div.text-center p.t-size-medium")
        if state_p is not None:
            state_text = state_p.get_text(" ", strip=True)
        mode_p = soup.select_one("div.text-center p.text-blue-grey-light")
        if mode_p is not None:
            mode_text = mode_p.get_text(" ", strip=True)

        info = self._parse_info_rows(soup)
        status = LegrandGreenUpStationStatus(
            state_text=state_text,
            mode_text=mode_text,
            max_charging_current_a=self._first_float(info, ["corrente massima di caricamento", "max charging current"]),
            cable_max_current_a=self._first_float(info, ["corrente cavo max", "max cable current"]),
            requested_current_a=self._first_float(info, ["corrente richiesta", "requested current"]),
            instantaneous_current_a=self._first_float(
                info, ["corrente ricarica istantanea", "instantaneous charging current"]
            ),
            instantaneous_power_kva=self._first_float(info, ["potenza istantanea", "instantaneous power"]),
        )
        status.connector_status = self._infer_connector_status(state_text or "", mode_text or "", html)
        return status

    def _parse_rfid_status_html(self, html: str) -> LegrandGreenUpRfidStatus:
        soup = BeautifulSoup(html, "html.parser")
        state_p = soup.select_one("div.text-center p.t-size-medium")
        station_state = state_p.get_text(" ", strip=True) if state_p is not None else None

        info = self._parse_info_rows(soup)
        enabled_raw = self._first_text(info, ["attivazione rfid", "rfid activation", "activation rfid"])
        enabled: bool | None = None
        if enabled_raw is not None:
            s = enabled_raw.strip().lower()
            if s in {"attivo", "active", "enabled", "on", "oui", "si"}:
                enabled = True
            elif s in {"disattivo", "inactive", "disabled", "off", "non", "no"}:
                enabled = False

        mode = self._first_text(info, ["programmazione badge", "badge programming"])

        return LegrandGreenUpRfidStatus(station_state=station_state, rfid_enabled=enabled, badge_programming_mode=mode)

    def _parse_info_rows(self, soup: BeautifulSoup) -> dict[str, str]:
        out: dict[str, str] = {}
        for row in soup.select("div.info-row"):
            cols = row.select("div.columns")
            if len(cols) < 2:
                continue
            label = cols[0].get_text(" ", strip=True)
            value = cols[1].get_text(" ", strip=True)
            if not label:
                continue
            out[_normalize_label(label)] = value
        return out

    def _first_text(self, values: dict[str, str], candidates: list[str]) -> str | None:
        for c in candidates:
            key = _normalize_label(c)
            for k, v in values.items():
                if k.startswith(key):
                    return v
        return None

    def _first_float(self, values: dict[str, str], candidates: list[str]) -> float | None:
        raw = self._first_text(values, candidates)
        if raw is None:
            return None
        return _parse_float(raw)

    def _infer_connector_status(self, state_text: str, mode_text: str, html: str) -> ConnectorStatus:
        s = f"{state_text} {mode_text} {html}".lower()
        if any(x in s for x in ["pronto", "ready", "available", "disponible"]):
            return ConnectorStatus.AVAILABLE
        if any(x in s for x in ["in carica", "charging", "en charge", "ricarica"]):
            return ConnectorStatus.CHARGING
        if any(x in s for x in ["occup", "occupied", "prise", "plugged", "conness"]):
            return ConnectorStatus.OCCUPIED
        if any(x in s for x in ["fault", "erreur", "errore", "défaut", "defaut"]):
            return ConnectorStatus.FAULTED
        return ConnectorStatus.UNKNOWN

    def _normalize_csv_header(self, header: str) -> str:
        h = header.strip().lower().replace("\ufeff", "")
        h = re.sub(r"\s+", " ", h)
        h = h.replace("’", "'")
        return h

    def _resolve_charge_session_headers(self, normalized_headers: set[str]) -> dict[str, str]:
        def pick(*candidates: str) -> str:
            for c in candidates:
                if c in normalized_headers:
                    return c
            raise LegrandGreenUpProtocolError(f"CSV is missing required column. Tried: {list(candidates)}")

        def maybe(*candidates: str) -> str | None:
            for c in candidates:
                if c in normalized_headers:
                    return c
            return None

        return {
            "start_time": pick(
                "start time",
                "start",
                "date start",
                "date début",
                "date debut",
                "inizio",
                "data inizio",
                "data e ora sessione d'inizio",
            ),
            "end_time": pick(
                "end time",
                "end",
                "date end",
                "date fin",
                "fine",
                "data fine",
                "data e ora sessione finale",
            ),
            "energy_wh": pick(
                "energy (wh)",
                "energy wh",
                "energy",
                "energie (wh)",
                "energie wh",
                "energia (wh)",
                "energia wh",
                "energie",
                "energia",
                "energia in wh",
            ),
            "total_minutes": pick(
                "total minutes",
                "minutes total",
                "minuti totali",
                "durée totale",
                "duree totale",
                "total",
                "tempo totale in min",
            ),
            "charging_minutes": pick(
                "charging minutes",
                "minutes charge",
                "minuti carica",
                "durée charge",
                "duree charge",
                "charging",
                "tempo di ricarica in min",
            ),
            "idle_minutes": pick(
                "idle minutes",
                "minutes idle",
                "minuti attesa",
                "minutes attente",
                "durée attente",
                "duree attente",
                "idle",
                "tempo senza ricarica in min",
            ),
            "plug_type": maybe("plug type", "type prise", "tipo presa", "tipo di spina", "presa", "prise"),
            "rfid_id": maybe("rfid id", "id rfid", "badge id", "id badge", "id (se si usa rfid)"),
            "rfid_name": maybe("rfid name", "nom rfid", "nome rfid", "badge name", "nom badge", "nome (se si usa rfid)"),
        }

    def _row_to_charging_session(
        self,
        row: dict[str, Any],
        resolved_headers: dict[str, str],
    ) -> ChargingSession:
        def get(name: str) -> str:
            key = resolved_headers[name]
            actual = None
            for k, v in row.items():
                if self._normalize_csv_header(k) == key:
                    actual = v
                    break
            if actual is None:
                raise LegrandGreenUpProtocolError(f"Missing value for {name}")
            if not isinstance(actual, str):
                actual = str(actual)
            return actual.strip()

        def get_optional(name: str) -> str | None:
            key = resolved_headers.get(name)
            if key is None:
                return None
            for k, v in row.items():
                if self._normalize_csv_header(k) == key:
                    if v is None:
                        return None
                    s = str(v).strip()
                    return s if s != "" else None
            return None

        start = _parse_datetime(get("start_time"))
        end = _parse_datetime(get("end_time"))
        if start is None or end is None:
            raise LegrandGreenUpProtocolError("Unparseable start_time/end_time")

        energy_wh = _parse_int(get("energy_wh"))
        if energy_wh is None:
            raise LegrandGreenUpProtocolError("Unparseable energy_wh")

        total = _parse_duration_minutes(get("total_minutes"))
        charging = _parse_duration_minutes(get("charging_minutes"))
        idle = _parse_duration_minutes(get("idle_minutes"))
        if total is None or charging is None or idle is None:
            raise LegrandGreenUpProtocolError("Unparseable minutes columns")

        return ChargingSession(
            start_time=start,
            end_time=end,
            energy_wh=energy_wh,
            total_minutes=total,
            charging_minutes=charging,
            idle_minutes=idle,
            plug_type=get_optional("plug_type"),
            rfid_id=get_optional("rfid_id"),
            rfid_name=get_optional("rfid_name"),
        )


def as_driver() -> StationDriver:
    return LegrandGreenUpDriver()
