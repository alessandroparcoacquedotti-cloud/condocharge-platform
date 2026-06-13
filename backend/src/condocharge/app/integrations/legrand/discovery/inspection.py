from __future__ import annotations

import json
import re

from condocharge.app.integrations.legrand.discovery.models import ContentKind, ResponseSnapshot

_XML_PREFIX = re.compile(rb"^\s*<\?xml\b", re.IGNORECASE)
_XML_TAG = re.compile(rb"^\s*<([a-zA-Z_][\w\-.]*)(\s|>|/)", re.DOTALL)
_HTML_DOCTYPE = re.compile(rb"^\s*<!doctype\s+html\b", re.IGNORECASE)
_HTML_TAG = re.compile(rb"^\s*<html(\s|>|/)", re.IGNORECASE)


def normalize_headers(headers: dict[str, str]) -> dict[str, str]:
    return {k.lower(): v for k, v in headers.items()}


def content_type_from_headers(headers: dict[str, str]) -> str | None:
    return normalize_headers(headers).get("content-type")


def content_length_from_headers(headers: dict[str, str]) -> int | None:
    value = normalize_headers(headers).get("content-length")
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def is_redirect(status_code: int) -> bool:
    return status_code in {301, 302, 303, 307, 308}


def redirect_location(headers: dict[str, str]) -> str | None:
    return normalize_headers(headers).get("location")


def sniff_content_kind(snapshot: ResponseSnapshot) -> ContentKind:
    ct = content_type_from_headers(snapshot.headers) or ""
    ct_l = ct.lower()
    if "application/json" in ct_l or ct_l.endswith("+json"):
        return ContentKind.JSON
    if "application/xml" in ct_l or "text/xml" in ct_l or ct_l.endswith("+xml"):
        return ContentKind.XML
    if "text/html" in ct_l:
        return ContentKind.HTML
    if ct_l.startswith("text/"):
        return ContentKind.TEXT

    body = snapshot.body[:4096]
    if not body:
        return ContentKind.UNKNOWN
    if _HTML_DOCTYPE.match(body) or _HTML_TAG.match(body):
        return ContentKind.HTML
    if _XML_PREFIX.match(body) or _XML_TAG.match(body):
        return ContentKind.XML

    try:
        json.loads(body.decode("utf-8"))
        return ContentKind.JSON
    except Exception:
        pass

    if _is_mostly_text(body):
        return ContentKind.TEXT
    return ContentKind.BINARY


def _is_mostly_text(sample: bytes) -> bool:
    if not sample:
        return True
    printable = 0
    for b in sample:
        if b in (9, 10, 13) or 32 <= b <= 126:
            printable += 1
    return (printable / len(sample)) >= 0.9
