from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import traceback
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, unquote, urlsplit

from playwright.sync_api import (
    BrowserContext,
    Page,
    Request,
    Response,
    TimeoutError,
    sync_playwright,
)

DEFAULT_TARGETS = ["http://192.168.1.200", "http://192.168.1.201"]
DEFAULT_PROFILE = "default"
HISTORY_CAPTURE_PROFILE = "history_capture"


@dataclass(frozen=True)
class CapturedBody:
    text: str | None
    base64: str | None
    truncated: bool


@dataclass(frozen=True)
class CapturedRequest:
    id: str
    timestamp: str
    method: str
    url: str
    host: str
    path: str
    query: dict[str, list[str]]
    headers: dict[str, str]
    post_data: CapturedBody | None
    redirected_from: str | None


@dataclass(frozen=True)
class CapturedResponse:
    request_id: str
    timestamp: str
    url: str
    status: int
    status_text: str
    headers: dict[str, str]
    content_type: str | None
    body_preview: CapturedBody | None


@dataclass(frozen=True)
class BrowserCaptureReport:
    generated_at: str
    profile: str
    targets: list[str]
    har_path: str
    json_path: str
    request_count: int
    response_count: int
    cookies: list[dict[str, Any]]
    storage_state: dict[str, Any]
    requests: list[CapturedRequest]
    responses: list[CapturedResponse]


@dataclass(frozen=True)
class CaptureProfile:
    name: str
    default_json_path: Path
    instructions: list[str]


@dataclass(frozen=True)
class HistoryCaptureFinding:
    categories: list[str]
    url: str
    method: str
    parameters: dict[str, list[str]]
    content_type: str | None
    filename: str | None
    response_size_bytes: int | None
    response_size_exact: bool
    status: int


@dataclass(frozen=True)
class HistoryCaptureReport:
    generated_at: str
    profile: str
    targets: list[str]
    har_path: str
    json_path: str
    request_count: int
    response_count: int
    cookies: list[dict[str, Any]]
    storage_state: dict[str, Any]
    download_endpoints: list[HistoryCaptureFinding]
    export_endpoints: list[HistoryCaptureFinding]
    csv_responses: list[HistoryCaptureFinding]
    attachment_responses: list[HistoryCaptureFinding]
    rfid_user_data: list[HistoryCaptureFinding]
    charge_session_data: list[HistoryCaptureFinding]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _reports_dir() -> Path:
    return _repo_root() / "reports"


def _default_json_path(profile_name: str = DEFAULT_PROFILE) -> Path:
    if profile_name == HISTORY_CAPTURE_PROFILE:
        return _reports_dir() / "legrand_history_capture.json"
    return _reports_dir() / "legrand_browser_capture.json"


def _default_har_path() -> Path:
    return _reports_dir() / "legrand_browser_capture.har"


def _iso_now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _print_info(message: str) -> None:
    print(message, flush=True)


def _print_error(message: str, exc: BaseException | None = None) -> None:
    print(message, file=sys.stderr, flush=True)
    if exc is not None:
        traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)


def _capture_profile(name: str) -> CaptureProfile:
    if name == HISTORY_CAPTURE_PROFILE:
        return CaptureProfile(
            name=HISTORY_CAPTURE_PROFILE,
            default_json_path=_default_json_path(HISTORY_CAPTURE_PROFILE),
            instructions=[
                "Login.",
                "Open Historique page.",
                "Trigger charge session export.",
                "Trigger history download.",
                "Trigger CSV export.",
                "Open RFID page.",
                "Trigger RFID export.",
                "Trigger badge download.",
                "Trigger badge list download.",
                "Close all browser pages created by this tool to finish and write reports.",
            ],
        )

    return CaptureProfile(
        name=DEFAULT_PROFILE,
        default_json_path=_default_json_path(DEFAULT_PROFILE),
        instructions=[
            "Use the opened browser to log in and navigate manually.",
            "Close all browser pages created by this tool to finish and write reports.",
        ],
    )



def _headers_to_dict(headers: dict[str, str]) -> dict[str, str]:
    return dict(headers)


def _decode_or_base64(data: bytes, *, max_bytes: int) -> CapturedBody:
    truncated = len(data) > max_bytes
    chunk = data[:max_bytes]
    try:
        text = chunk.decode("utf-8")
        return CapturedBody(text=text, base64=None, truncated=truncated)
    except UnicodeDecodeError:
        return CapturedBody(text=None, base64=base64.b64encode(chunk).decode("ascii"), truncated=truncated)


def _request_post_data(request: Request, *, max_bytes: int) -> CapturedBody | None:
    if request.method.upper() in {"GET", "HEAD"}:
        return None
    try:
        buf = request.post_data_buffer
    except Exception as exc:
        _print_error(f"Failed to read request body buffer for {request.method} {request.url}", exc)
        buf = None
    if buf:
        return _decode_or_base64(buf, max_bytes=max_bytes)
    try:
        post_data = request.post_data
    except Exception as exc:
        _print_error(f"Failed to read request post data for {request.method} {request.url}", exc)
        return None
    if post_data:
        return _decode_or_base64(post_data.encode("utf-8", errors="replace"), max_bytes=max_bytes)
    return None


def _response_body_preview(response: Response, *, max_bytes: int) -> CapturedBody | None:
    try:
        buf = response.body()
    except Exception as exc:
        _print_error(f"Failed to read response body for {response.status} {response.url}", exc)
        return None
    if not buf:
        return None
    return _decode_or_base64(buf, max_bytes=max_bytes)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="legrand_browser_inspector", add_help=True)
    parser.add_argument("--profile", choices=[DEFAULT_PROFILE, HISTORY_CAPTURE_PROFILE], default=DEFAULT_PROFILE)
    parser.add_argument("--targets", nargs="*", default=DEFAULT_TARGETS)
    parser.add_argument("--json-output")
    parser.add_argument("--har-output", default=str(_default_har_path()))
    parser.add_argument("--max-body-bytes", type=int, default=8192)
    parser.add_argument("--slowmo-ms", type=int, default=0)
    return parser.parse_args(argv)


def _open_targets(context: BrowserContext, targets: list[str]) -> list[Page]:
    pages: list[Page] = []
    for target in targets:
        try:
            page = context.new_page()
            page.goto(target, wait_until="domcontentloaded")
            pages.append(page)
        except Exception as exc:
            _print_error(f"Failed to open target {target}", exc)
    return pages


def _page_is_closed(page: Page) -> bool:
    try:
        return page.is_closed()
    except Exception as exc:
        _print_error("Failed to query page closed state.", exc)
        return True


def _wait_for_operator(tracked_pages: list[Page]) -> None:
    while True:
        open_pages = 0
        for page in tracked_pages:
            if not _page_is_closed(page):
                open_pages += 1

        if open_pages <= 0:
            return

        pump_page: Page | None = None
        for page in tracked_pages:
            if not _page_is_closed(page):
                pump_page = page
                break

        if pump_page is None:
            return

        try:
            pump_page.wait_for_timeout(250)
        except TimeoutError:
            pass
        except Exception as exc:
            if _page_is_closed(pump_page):
                continue
            _print_error("Wait loop failed while pumping events.", exc)
            return


def _print_profile_instructions(profile: CaptureProfile) -> None:
    _print_info(f"Capture profile: {profile.name}")
    for index, instruction in enumerate(profile.instructions, start=1):
        _print_info(f"{index}. {instruction}")


def _request_parameters(request: CapturedRequest) -> dict[str, list[str]]:
    params = {key: list(values) for key, values in request.query.items()}
    post_text = request.post_data.text if request.post_data and request.post_data.text is not None else None
    if not post_text:
        return params

    for key, values in parse_qs(post_text, keep_blank_values=True).items():
        params.setdefault(key, []).extend(values)
    return params


def _response_header_value(response: CapturedResponse, header_name: str) -> str | None:
    for key, value in response.headers.items():
        if key.lower() == header_name.lower():
            return value
    return None


def _response_filename(response: CapturedResponse) -> str | None:
    content_disposition = _response_header_value(response, "content-disposition")
    if not content_disposition:
        return None

    match = re.search(r"filename\*?=(?:UTF-8''|\"?)([^\";]+)", content_disposition, flags=re.IGNORECASE)
    if not match:
        return None
    return unquote(match.group(1).strip().strip('"'))


def _response_size_bytes(response: CapturedResponse) -> tuple[int | None, bool]:
    content_length = _response_header_value(response, "content-length")
    if content_length is not None:
        try:
            return int(content_length), True
        except ValueError as exc:
            _print_error(f"Invalid content-length header for {response.url}: {content_length}", exc)

    body = response.body_preview
    if body is None:
        return None, False

    if body.base64 is not None:
        try:
            return len(base64.b64decode(body.base64)), not body.truncated
        except Exception as exc:
            _print_error(f"Failed to decode base64 body preview for {response.url}", exc)
            return None, False

    if body.text is not None:
        return len(body.text.encode("utf-8")), not body.truncated

    return None, False


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


def _build_default_report(
    *,
    profile_name: str,
    targets: list[str],
    har_path: Path,
    json_path: Path,
    cookies: list[dict[str, Any]],
    storage_state: dict[str, Any],
    requests: list[CapturedRequest],
    responses: list[CapturedResponse],
) -> dict[str, Any]:
    report = BrowserCaptureReport(
        generated_at=_iso_now(),
        profile=profile_name,
        targets=targets,
        har_path=str(har_path),
        json_path=str(json_path),
        request_count=len(requests),
        response_count=len(responses),
        cookies=cookies,
        storage_state=storage_state,
        requests=requests,
        responses=responses,
    )
    return asdict(report)


def _history_capture_finding(request: CapturedRequest, response: CapturedResponse) -> HistoryCaptureFinding | None:
    parameters = _request_parameters(request)
    filename = _response_filename(response)
    response_size_bytes, response_size_exact = _response_size_bytes(response)
    content_type = response.content_type
    content_type_lower = (content_type or "").lower()
    filename_lower = filename.lower() if filename else ""
    content_disposition = (_response_header_value(response, "content-disposition") or "").lower()

    request_tokens = [request.url.lower(), request.path.lower()]
    for key, values in parameters.items():
        request_tokens.append(key.lower())
        request_tokens.extend(value.lower() for value in values)
    request_search = " ".join(request_tokens)

    body_text = ""
    if response.body_preview and response.body_preview.text is not None:
        body_text = response.body_preview.text.lower()
    response_search = " ".join([content_type_lower, filename_lower, content_disposition, body_text])

    categories: list[str] = []
    if (
        _contains_any(request_search, ("download", "export", "csv"))
        or "attachment" in content_disposition
        or filename is not None
    ):
        categories.append("download_endpoints")

    if (
        _contains_any(request_search, ("download", "export", "csv"))
        or "attachment" in content_disposition
        or filename_lower.endswith(".csv")
        or "csv" in content_type_lower
    ):
        categories.append("export_endpoints")

    if "csv" in content_type_lower or filename_lower.endswith(".csv"):
        categories.append("csv_responses")

    if "attachment" in content_disposition or filename is not None:
        categories.append("attachment_responses")

    if _contains_any(request_search, ("rfid", "badge")) or _contains_any(
        response_search,
        ("attivazione rfid", "programmazione badge", "saverfidlist", "badge", "rfid"),
    ):
        categories.append("rfid_user_data")

    if _contains_any(request_search, ("chargesession", "historique", "history")) or _contains_any(
        response_search,
        ("dati ricarica memorizzati", "chargesession", "historique"),
    ):
        categories.append("charge_session_data")

    if not categories:
        return None

    return HistoryCaptureFinding(
        categories=categories,
        url=request.url,
        method=request.method,
        parameters=parameters,
        content_type=content_type,
        filename=filename,
        response_size_bytes=response_size_bytes,
        response_size_exact=response_size_exact,
        status=response.status,
    )


def _build_history_capture_report(
    *,
    profile_name: str,
    targets: list[str],
    har_path: Path,
    json_path: Path,
    cookies: list[dict[str, Any]],
    storage_state: dict[str, Any],
    requests: list[CapturedRequest],
    responses: list[CapturedResponse],
) -> dict[str, Any]:
    responses_by_request_id = {response.request_id: response for response in responses}
    findings: list[HistoryCaptureFinding] = []

    for request in requests:
        response = responses_by_request_id.get(request.id)
        if response is None:
            continue
        finding = _history_capture_finding(request, response)
        if finding is not None:
            findings.append(finding)

    category_map: dict[str, list[HistoryCaptureFinding]] = {
        "download_endpoints": [],
        "export_endpoints": [],
        "csv_responses": [],
        "attachment_responses": [],
        "rfid_user_data": [],
        "charge_session_data": [],
    }
    for finding in findings:
        for category in finding.categories:
            category_map[category].append(finding)

    report = HistoryCaptureReport(
        generated_at=_iso_now(),
        profile=profile_name,
        targets=targets,
        har_path=str(har_path),
        json_path=str(json_path),
        request_count=len(requests),
        response_count=len(responses),
        cookies=cookies,
        storage_state=storage_state,
        download_endpoints=category_map["download_endpoints"],
        export_endpoints=category_map["export_endpoints"],
        csv_responses=category_map["csv_responses"],
        attachment_responses=category_map["attachment_responses"],
        rfid_user_data=category_map["rfid_user_data"],
        charge_session_data=category_map["charge_session_data"],
    )
    return asdict(report)


def _build_report(
    *,
    profile_name: str,
    targets: list[str],
    har_path: Path,
    json_path: Path,
    cookies: list[dict[str, Any]],
    storage_state: dict[str, Any],
    requests: list[CapturedRequest],
    responses: list[CapturedResponse],
) -> dict[str, Any]:
    if profile_name == HISTORY_CAPTURE_PROFILE:
        return _build_history_capture_report(
            profile_name=profile_name,
            targets=targets,
            har_path=har_path,
            json_path=json_path,
            cookies=cookies,
            storage_state=storage_state,
            requests=requests,
            responses=responses,
        )

    return _build_default_report(
        profile_name=profile_name,
        targets=targets,
        har_path=har_path,
        json_path=json_path,
        cookies=cookies,
        storage_state=storage_state,
        requests=requests,
        responses=responses,
    )


def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    profile_name = str(args.profile)
    profile = _capture_profile(profile_name)
    targets = list(dict.fromkeys([str(t).strip().rstrip("/") for t in args.targets if str(t).strip()]))
    json_path = Path(str(args.json_output)) if args.json_output else profile.default_json_path
    har_path = Path(str(args.har_output))
    max_body_bytes = int(args.max_body_bytes)
    slowmo_ms = int(args.slowmo_ms)

    try:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        har_path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        _print_error("Failed to create output directories.", exc)
        return 1

    requests: list[CapturedRequest] = []
    responses: list[CapturedResponse] = []
    id_by_request_obj: dict[int, str] = {}
    seq = 0
    cookies: list[dict[str, Any]] = []
    storage_state: dict[str, Any] = {}
    har_write_ok = False
    json_write_ok = False

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=slowmo_ms)
        context = browser.new_context(
            record_har_path=str(har_path),
            record_har_content="embed",
        )

        def on_request(request: Request) -> None:
            nonlocal seq
            try:
                seq += 1
                req_id = f"r{seq}"
                id_by_request_obj[id(request)] = req_id

                parts = urlsplit(request.url)
                query = {k: v for k, v in parse_qs(parts.query, keep_blank_values=True).items()}
                redirected_from = request.redirected_from.url if request.redirected_from else None

                requests.append(
                    CapturedRequest(
                        id=req_id,
                        timestamp=_iso_now(),
                        method=request.method,
                        url=request.url,
                        host=parts.hostname or "",
                        path=parts.path,
                        query=query,
                        headers=_headers_to_dict(request.headers),
                        post_data=_request_post_data(request, max_bytes=max_body_bytes),
                        redirected_from=redirected_from,
                    )
                )
            except Exception as exc:
                _print_error(f"Failed to capture request {request.method} {request.url}", exc)

        def on_response(response: Response) -> None:
            nonlocal seq
            try:
                req = response.request
                req_id = id_by_request_obj.get(id(req))
                if req_id is None:
                    seq += 1
                    req_id = f"r{seq}"
                    id_by_request_obj[id(req)] = req_id

                headers = _headers_to_dict(response.headers)
                content_type = headers.get("content-type") or headers.get("Content-Type")

                responses.append(
                    CapturedResponse(
                        request_id=req_id,
                        timestamp=_iso_now(),
                        url=response.url,
                        status=int(response.status),
                        status_text=response.status_text or "",
                        headers=headers,
                        content_type=content_type,
                        body_preview=_response_body_preview(response, max_bytes=max_body_bytes),
                    )
                )
            except Exception as exc:
                _print_error(f"Failed to capture response {response.status} {response.url}", exc)

        context.on("request", on_request)
        context.on("response", on_response)

        tracked_pages = _open_targets(context, targets)

        _print_info("Capture started")
        _print_profile_instructions(profile)

        try:
            _wait_for_operator(tracked_pages)
        except KeyboardInterrupt:
            _print_error("Capture interrupted by operator. Continuing with report export.")
        finally:
            try:
                cookies = cast(list[dict[str, Any]], context.cookies())
            except Exception as exc:
                _print_error("Failed to collect browser cookies.", exc)
                cookies = []

            try:
                storage_state = cast(dict[str, Any], context.storage_state())
            except Exception as exc:
                _print_error("Failed to collect browser storage state.", exc)
                storage_state = {}

            _print_info(f"Request count: {len(requests)}")
            _print_info(f"Response count: {len(responses)}")
            _print_info("Writing HAR report")

            try:
                context.close()
                har_write_ok = har_path.exists()
                if not har_write_ok:
                    _print_error(f"HAR report was not created at {har_path}")
            except Exception as exc:
                _print_error(f"Failed to write HAR report to {har_path}", exc)

            try:
                browser.close()
            except Exception as exc:
                _print_error("Failed to close browser.", exc)

    report = _build_report(
        profile_name=profile_name,
        targets=targets,
        har_path=har_path,
        json_path=json_path,
        cookies=cookies,
        storage_state=storage_state,
        requests=requests,
        responses=responses,
    )

    _print_info("Writing JSON report")
    try:
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        json_write_ok = True
    except Exception as exc:
        _print_error(f"Failed to write JSON report to {json_path}", exc)

    _print_info("Capture completed")
    _print_info(f"JSON report path: {json_path}")
    _print_info(f"HAR report path: {har_path}")

    if not json_write_ok:
        return 1
    if not har_write_ok:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
