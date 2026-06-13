from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

DEFAULT_HOSTS = ["192.168.1.200", "192.168.1.201"]
BASE_PROBE_PATHS = ["/", "/index.html", "/status", "/api", "/api/status", "/json", "/xml"]

MAX_ANALYSIS_BYTES = 262_144
MAX_TEXT_ANALYSIS_CHARS = 200_000

_IGNORE_PREFIXES = ("javascript:", "mailto:", "tel:", "data:", "#")

_ENDPOINT_CANDIDATE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"""https?://[^\s"'<>]+""", re.IGNORECASE),
    re.compile(r"""(?:"|')(/(?:api|rest|services)/[^"'<>]+)(?:"|')""", re.IGNORECASE),
    re.compile(r"""(?:"|')(/[^"'<>]+\.(?:php|json|jsp|do))(?:"|')""", re.IGNORECASE),
    re.compile(r"""fetch\(\s*(?:"|')([^"'<>]+)(?:"|')""", re.IGNORECASE),
    re.compile(
        r"""\.open\(\s*(?:"|')(?:GET|POST|PUT|DELETE|PATCH)(?:"|')\s*,\s*(?:"|')([^"'<>]+)(?:"|')""",
        re.IGNORECASE,
    ),
    re.compile(r"""\$\.ajax\([^)]*?url\s*:\s*(?:"|')([^"'<>]+)(?:"|')""", re.IGNORECASE | re.DOTALL),
]


@dataclass(frozen=True)
class ProbeResult:
    url: str
    final_url: str | None
    status_code: int | None
    content_type: str | None
    content_length: int | None
    server: str | None
    redirect_target: str | None
    body_preview: str | None
    elapsed_ms: int | None
    error: str | None


@dataclass(frozen=True)
class HomepageMetadata:
    url: str
    title: str | None
    script_src: list[str]
    link_href: list[str]
    form_action: list[str]
    iframe_src: list[str]
    anchor_href: list[str]


@dataclass(frozen=True)
class AssetRecord:
    url: str
    kind: str
    probe: ProbeResult
    extracted_candidates: list[str]


@dataclass(frozen=True)
class CandidateEndpoint:
    value: str
    normalized_path: str
    sources: list[str]


@dataclass(frozen=True)
class TargetDeepReport:
    base_url: str
    homepage: ProbeResult
    homepage_metadata: HomepageMetadata | None
    base_probe_results: list[ProbeResult]
    discovered_assets: list[AssetRecord]
    javascript_files: list[str]
    endpoint_candidates: list[CandidateEndpoint]
    candidate_probe_results: list[ProbeResult]


@dataclass(frozen=True)
class DeepDiscoveryReport:
    generated_at: str
    timeout_seconds: float
    follow_redirects: bool
    verify_tls: bool
    max_body_chars: int
    max_assets: int
    max_candidate_probes: int
    targets: list[TargetDeepReport]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _safe_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _decode_text(content: bytes, *, limit: int) -> str:
    if not content:
        return ""
    text = content.decode("utf-8", errors="replace")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _fmt_header(headers: httpx.Headers, name: str) -> str | None:
    value = headers.get(name)
    return value if value is not None and value != "" else None


def probe_once(
    *,
    client: httpx.Client,
    url: str,
    max_body_chars: int,
) -> tuple[ProbeResult, bytes]:
    body = bytearray()
    try:
        with client.stream("GET", url) as response:
            for chunk in response.iter_bytes():
                if not chunk:
                    continue
                remaining = MAX_ANALYSIS_BYTES - len(body)
                if remaining <= 0:
                    break
                body.extend(chunk[:remaining])

        history_last = response.history[-1] if response.history else None
        redirect_target = _fmt_header(history_last.headers, "Location") if history_last else None

        content_type = _fmt_header(response.headers, "Content-Type")
        content_length = _safe_int(_fmt_header(response.headers, "Content-Length"))
        server = _fmt_header(response.headers, "Server")

        preview = None
        try:
            preview = _decode_text(bytes(body), limit=max_body_chars)
        except Exception:
            preview = None

        elapsed_ms = int(response.elapsed.total_seconds() * 1000)
        return (
            ProbeResult(
                url=url,
                final_url=str(response.url),
                status_code=response.status_code,
                content_type=content_type,
                content_length=content_length,
                server=server,
                redirect_target=redirect_target,
                body_preview=preview,
                elapsed_ms=elapsed_ms,
                error=None,
            ),
            bytes(body),
        )
    except Exception as e:
        return (
            ProbeResult(
                url=url,
                final_url=None,
                status_code=None,
                content_type=None,
                content_length=None,
                server=None,
                redirect_target=None,
                body_preview=None,
                elapsed_ms=None,
                error=f"{type(e).__name__}: {e}",
            ),
            bytes(body),
        )


def _is_html(content_type: str | None, preview: str | None) -> bool:
    if content_type and "text/html" in content_type.lower():
        return True
    if preview:
        s = preview.lstrip().lower()
        return s.startswith("<!doctype html") or s.startswith("<html") or "<title" in s
    return False


def _extract_homepage_metadata(*, url: str, html: str) -> HomepageMetadata:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.string.strip() if soup.title and soup.title.string else None

    script_src = [t.get("src") for t in soup.find_all("script") if t.get("src")]
    link_href = [t.get("href") for t in soup.find_all("link") if t.get("href")]
    form_action = [t.get("action") for t in soup.find_all("form") if t.get("action")]
    iframe_src = [t.get("src") for t in soup.find_all("iframe") if t.get("src")]
    anchor_href = [t.get("href") for t in soup.find_all("a") if t.get("href")]

    return HomepageMetadata(
        url=url,
        title=title,
        script_src=script_src,
        link_href=link_href,
        form_action=form_action,
        iframe_src=iframe_src,
        anchor_href=anchor_href,
    )


def _normalize_local_url(base_url: str, raw: str) -> str | None:
    raw = raw.strip()
    if not raw or raw.startswith(_IGNORE_PREFIXES):
        return None

    joined = urljoin(base_url + "/", raw)
    base_parts = urlsplit(base_url)
    parts = urlsplit(joined)

    if parts.scheme not in {"http", "https"}:
        return None
    if parts.netloc != base_parts.netloc:
        return None

    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def _normalize_local_path(base_url: str, raw: str) -> str | None:
    normalized = _normalize_local_url(base_url, raw)
    if normalized is None:
        return None
    parts = urlsplit(normalized)
    if not parts.path.startswith("/"):
        return None
    return parts.path + (f"?{parts.query}" if parts.query else "")


def _guess_asset_kind(url: str) -> str:
    path = urlsplit(url).path.lower()
    if path.endswith(".js"):
        return "js"
    if path.endswith(".css"):
        return "css"
    if path.endswith((".html", ".htm")):
        return "html"
    if path.endswith((".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico")):
        return "image"
    if path.endswith((".woff", ".woff2", ".ttf", ".eot", ".otf")):
        return "font"
    return "other"


def _should_fetch_asset(url: str) -> bool:
    path = urlsplit(url).path.lower()
    if path.startswith("/assets/"):
        return True
    return path.endswith((".js", ".css", ".map"))


def _is_static_asset_path(path_with_query: str) -> bool:
    path = path_with_query.split("?", 1)[0].lower()
    if path.startswith("/assets/"):
        return True
    return path.endswith(
        (
            ".js",
            ".css",
            ".map",
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".svg",
            ".webp",
            ".ico",
            ".woff",
            ".woff2",
            ".ttf",
            ".eot",
            ".otf",
        )
    )


def _extract_endpoint_candidates(text: str) -> list[str]:
    out: list[str] = []
    for pattern in _ENDPOINT_CANDIDATE_PATTERNS:
        for match in pattern.finditer(text):
            if match.groups():
                out.append(match.group(1))
            else:
                out.append(match.group(0))
    return out


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        if v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


def _print_terminal_report(report: DeepDiscoveryReport) -> None:
    print(
        "CondoCharge Legrand Deep Probe\n"
        f"Generated: {report.generated_at}\n"
        f"Timeout: {report.timeout_seconds}s | Redirects: {report.follow_redirects} | TLS verify: {report.verify_tls}\n"
    )

    for t in report.targets:
        title = t.homepage_metadata.title if t.homepage_metadata else None
        print(f"Target: {t.base_url}")
        print(f"  Homepage: {t.homepage.status_code or 'ERROR'} | Title: {title or '-'}")
        print(
            f"  Assets fetched: {len(t.discovered_assets)} | JS files: {len(t.javascript_files)} | "
            f"Candidates: {len(t.endpoint_candidates)} | Candidate probes: {len(t.candidate_probe_results)}"
        )

        interesting = [
            r
            for r in t.candidate_probe_results
            if r.error is None and r.status_code is not None and r.status_code not in {404}
        ]
        if interesting:
            print("  Interesting candidate responses:")
            for r in interesting[:20]:
                print(f"    {r.status_code} {r.url} ({r.content_type or '-'})")
        print("")


def _write_json_report(report: DeepDiscoveryReport, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = asdict(report)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="legrand_probe", add_help=True)
    parser.add_argument("--hosts", nargs="*", default=DEFAULT_HOSTS)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--schemes", nargs="*", default=["http"])
    parser.add_argument("--verify-tls", action="store_true", default=False)
    parser.add_argument("--max-body-chars", type=int, default=500)
    parser.add_argument("--max-assets", type=int, default=80)
    parser.add_argument("--max-candidate-probes", type=int, default=120)
    parser.add_argument("--output", default=str(_repo_root() / "reports" / "legrand_deep_discovery_report.json"))
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    hosts: list[str] = list(dict.fromkeys(args.hosts))
    schemes: list[str] = [s.lower() for s in args.schemes]
    timeout_seconds: float = float(args.timeout)
    max_body_chars: int = int(args.max_body_chars)
    max_assets: int = int(args.max_assets)
    max_candidate_probes: int = int(args.max_candidate_probes)
    output_path = Path(args.output)

    follow_redirects = True
    verify_tls = bool(args.verify_tls)

    targets: list[TargetDeepReport] = []

    timeout = httpx.Timeout(timeout_seconds)
    with httpx.Client(
        follow_redirects=follow_redirects,
        timeout=timeout,
        verify=verify_tls,
        headers={"User-Agent": "CondoCharge-LegrandProbe/0.3"},
    ) as client:
        for host in hosts:
            for scheme in schemes:
                base_url = f"{scheme}://{host}"

                homepage_url = f"{base_url}/"
                homepage, homepage_body = probe_once(client=client, url=homepage_url, max_body_chars=max_body_chars)

                homepage_metadata: HomepageMetadata | None = None
                extracted_asset_urls: list[str] = []
                homepage_candidates: list[str] = []

                if homepage.error is None and _is_html(homepage.content_type, homepage.body_preview):
                    html = _decode_text(homepage_body, limit=MAX_TEXT_ANALYSIS_CHARS)
                    homepage_metadata = _extract_homepage_metadata(url=homepage_url, html=html)

                    raw_urls: list[str] = []
                    raw_urls.extend(homepage_metadata.script_src)
                    raw_urls.extend(homepage_metadata.link_href)
                    raw_urls.extend(homepage_metadata.form_action)
                    raw_urls.extend(homepage_metadata.iframe_src)
                    raw_urls.extend(homepage_metadata.anchor_href)

                    homepage_candidates.extend(raw_urls)
                    homepage_candidates.extend(_extract_endpoint_candidates(html))

                    for raw in raw_urls:
                        normalized_url = _normalize_local_url(base_url, raw)
                        if normalized_url and _should_fetch_asset(normalized_url):
                            extracted_asset_urls.append(normalized_url)

                base_probe_results = [
                    probe_once(client=client, url=f"{base_url}{path}", max_body_chars=max_body_chars)[0]
                    for path in BASE_PROBE_PATHS
                ]

                discovered_assets: list[AssetRecord] = []
                js_files: list[str] = []
                asset_candidates: list[str] = []

                for asset_url in _dedupe_preserve_order(extracted_asset_urls)[:max_assets]:
                    probe, asset_body = probe_once(client=client, url=asset_url, max_body_chars=max_body_chars)
                    kind = _guess_asset_kind(asset_url)

                    extracted_from_asset: list[str] = []
                    if probe.error is None and kind in {"js", "html", "css", "other"}:
                        asset_text = _decode_text(asset_body, limit=MAX_TEXT_ANALYSIS_CHARS)
                        extracted_from_asset = _extract_endpoint_candidates(asset_text)

                    discovered_assets.append(
                        AssetRecord(
                            url=asset_url,
                            kind=kind,
                            probe=probe,
                            extracted_candidates=_dedupe_preserve_order(extracted_from_asset),
                        )
                    )
                    if kind == "js":
                        js_files.append(asset_url)
                    asset_candidates.extend(extracted_from_asset)

                all_raw_candidates = _dedupe_preserve_order(homepage_candidates + asset_candidates)

                candidate_map: dict[str, CandidateEndpoint] = {}
                for raw in all_raw_candidates:
                    normalized_path = _normalize_local_path(base_url, raw)
                    if normalized_path is None:
                        continue
                    key = normalized_path
                    sources: list[str] = []
                    if raw in homepage_candidates:
                        sources.append("homepage")
                    if raw in asset_candidates:
                        sources.append("assets")
                    existing = candidate_map.get(key)
                    if existing is None:
                        candidate_map[key] = CandidateEndpoint(
                            value=raw,
                            normalized_path=normalized_path,
                            sources=_dedupe_preserve_order(sources),
                        )
                    else:
                        candidate_map[key] = CandidateEndpoint(
                            value=existing.value,
                            normalized_path=existing.normalized_path,
                            sources=_dedupe_preserve_order(existing.sources + sources),
                        )

                endpoint_candidates = list(candidate_map.values())

                candidate_probe_urls = _dedupe_preserve_order(
                    [f"{base_url}{c.normalized_path}" for c in endpoint_candidates if not _is_static_asset_path(c.normalized_path)]
                )

                candidate_probe_results = [
                    probe_once(client=client, url=u, max_body_chars=max_body_chars)[0]
                    for u in candidate_probe_urls[:max_candidate_probes]
                ]

                targets.append(
                    TargetDeepReport(
                        base_url=base_url,
                        homepage=homepage,
                        homepage_metadata=homepage_metadata,
                        base_probe_results=base_probe_results,
                        discovered_assets=discovered_assets,
                        javascript_files=_dedupe_preserve_order(js_files),
                        endpoint_candidates=endpoint_candidates,
                        candidate_probe_results=candidate_probe_results,
                    )
                )

    report = DeepDiscoveryReport(
        generated_at=datetime.now(tz=UTC).isoformat(),
        timeout_seconds=timeout_seconds,
        follow_redirects=follow_redirects,
        verify_tls=verify_tls,
        max_body_chars=max_body_chars,
        max_assets=max_assets,
        max_candidate_probes=max_candidate_probes,
        targets=targets,
    )

    _print_terminal_report(report)
    _write_json_report(report, output_path)
    print(f"JSON report: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
