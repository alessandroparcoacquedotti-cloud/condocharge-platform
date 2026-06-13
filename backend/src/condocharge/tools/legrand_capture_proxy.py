from __future__ import annotations

import base64
import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from mitmproxy import ctx
from mitmproxy import http
from mitmproxy.options import Options
from mitmproxy.tools.dump import DumpMaster


DEFAULT_HOSTS = {"192.168.1.200", "192.168.1.201"}


@dataclass(frozen=True)
class CapturedMessageBody:
    text: str | None
    base64: str | None
    truncated: bool


@dataclass(frozen=True)
class CapturedRequest:
    method: str
    url: str
    host: str | None
    path: str
    query: dict[str, list[str]]
    headers: dict[str, str]
    body: CapturedMessageBody | None


@dataclass(frozen=True)
class CapturedResponse:
    status_code: int
    reason: str
    headers: dict[str, str]
    preview: CapturedMessageBody | None


@dataclass(frozen=True)
class CapturedFlow:
    captured_at: str
    request: CapturedRequest
    response: CapturedResponse | None
    error: str | None


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _default_output_path() -> Path:
    return _repo_root() / "reports" / "legrand_traffic_capture.json"


def _decode_or_base64(data: bytes, *, max_bytes: int) -> CapturedMessageBody:
    truncated = len(data) > max_bytes
    chunk = data[:max_bytes]
    try:
        text = chunk.decode("utf-8")
        return CapturedMessageBody(text=text, base64=None, truncated=truncated)
    except UnicodeDecodeError:
        return CapturedMessageBody(text=None, base64=base64.b64encode(chunk).decode("ascii"), truncated=truncated)


def _headers_to_dict(headers: http.Headers) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in headers.items(multi=True):
        key = k
        if key in out:
            out[key] = f"{out[key]}, {v}"
        else:
            out[key] = v
    return out


def _request_body(req: http.Request, *, max_bytes: int) -> CapturedMessageBody | None:
    if req.method.upper() in {"GET", "HEAD"}:
        return None
    content = req.raw_content or b""
    if not content:
        return None
    return _decode_or_base64(content, max_bytes=max_bytes)


def _response_preview(resp: http.Response, *, max_bytes: int) -> CapturedMessageBody | None:
    content = resp.raw_content or b""
    if not content:
        return None
    return _decode_or_base64(content, max_bytes=max_bytes)


class LegrandCaptureProxy:
    def __init__(self) -> None:
        self._flows: list[CapturedFlow] = []
        self._index_by_flow_id: dict[str, int] = {}

    def load(self, loader: Any) -> None:
        loader.add_option(
            name="legrand_hosts",
            typespec=str,
            default="192.168.1.200,192.168.1.201",
        )
        loader.add_option(
            name="legrand_capture_output",
            typespec=str,
            default=str(_default_output_path()),
        )
        loader.add_option(
            name="legrand_capture_max_bytes",
            typespec=int,
            default=4096,
        )

    def request(self, flow: http.HTTPFlow) -> None:
        if not self._should_capture(flow):
            return

        req = flow.request
        parts = urlsplit(req.url)
        query = {k: v for k, v in parse_qs(parts.query, keep_blank_values=True).items()}

        max_bytes = int(ctx.options.legrand_capture_max_bytes)
        captured = CapturedFlow(
            captured_at=datetime.now(tz=timezone.utc).isoformat(),
            request=CapturedRequest(
                method=req.method,
                url=req.url,
                host=req.host,
                path=parts.path,
                query=query,
                headers=_headers_to_dict(req.headers),
                body=_request_body(req, max_bytes=max_bytes),
            ),
            response=None,
            error=None,
        )
        self._flows.append(captured)
        self._index_by_flow_id[flow.id] = len(self._flows) - 1
        ctx.log.info(f"{req.method} {req.url}")

    def response(self, flow: http.HTTPFlow) -> None:
        if not self._should_capture(flow):
            return
        idx = self._index_by_flow_id.get(flow.id)
        if idx is None:
            return

        resp = flow.response
        if resp is None:
            return

        max_bytes = int(ctx.options.legrand_capture_max_bytes)
        last = self._flows[idx]
        updated = CapturedFlow(
            captured_at=last.captured_at,
            request=last.request,
            response=CapturedResponse(
                status_code=int(resp.status_code),
                reason=resp.reason or "",
                headers=_headers_to_dict(resp.headers),
                preview=_response_preview(resp, max_bytes=max_bytes),
            ),
            error=None,
        )
        self._flows[idx] = updated

    def error(self, flow: http.HTTPFlow) -> None:
        if not self._should_capture(flow):
            return
        idx = self._index_by_flow_id.get(flow.id)
        if idx is None:
            return

        last = self._flows[idx]
        err = flow.error
        updated = CapturedFlow(
            captured_at=last.captured_at,
            request=last.request,
            response=last.response,
            error=str(err) if err else "unknown_error",
        )
        self._flows[idx] = updated

    def done(self) -> None:
        output_path = Path(str(ctx.options.legrand_capture_output))
        output_path.parent.mkdir(parents=True, exist_ok=True)

        payload: dict[str, Any] = {
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "hosts": self._hosts(),
            "max_bytes": int(ctx.options.legrand_capture_max_bytes),
            "flows": [asdict(f) for f in self._flows],
        }
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        ctx.log.info(f"Wrote capture report: {output_path}")

    def _hosts(self) -> set[str]:
        raw = str(ctx.options.legrand_hosts)
        hosts = {h.strip() for h in raw.split(",") if h.strip()}
        return hosts or set(DEFAULT_HOSTS)

    def _should_capture(self, flow: http.HTTPFlow) -> bool:
        host = flow.request.host or ""
        return host in self._hosts()


addons = [LegrandCaptureProxy()]


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="legrand_capture_proxy", add_help=True)
    parser.add_argument("--listen-host", default="0.0.0.0")
    parser.add_argument("--listen-port", type=int, default=8080)
    parser.add_argument("--hosts", default="192.168.1.200,192.168.1.201")
    parser.add_argument("--output", default=str(_default_output_path()))
    parser.add_argument("--max-bytes", type=int, default=4096)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    opts = Options(listen_host=str(args.listen_host), listen_port=int(args.listen_port))
    master = DumpMaster(opts, with_termlog=True, with_dumper=False)

    addon = LegrandCaptureProxy()
    master.addons.add(addon)

    master.options.update(
        legrand_hosts=str(args.hosts),
        legrand_capture_output=str(args.output),
        legrand_capture_max_bytes=int(args.max_bytes),
    )

    try:
        master.run()
    except KeyboardInterrupt:
        pass
    finally:
        master.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
