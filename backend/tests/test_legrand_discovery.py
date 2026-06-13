from __future__ import annotations

from datetime import UTC, datetime

from condocharge.app.integrations.legrand.discovery.models import (
    HttpMethod,
    ProbeRequest,
    ProbeTarget,
    ResponseSnapshot,
)
from condocharge.app.integrations.legrand.discovery.service import LegrandDiscoveryService


class FakeTransport:
    def __init__(self, mapping: dict[str, ResponseSnapshot]) -> None:
        self._mapping = mapping

    def fetch(self, *, target: ProbeTarget, request: ProbeRequest) -> ResponseSnapshot:
        url = f"{target.base_url()}{request.path}"
        return self._mapping[url]


def test_discovery_classifies_html_json_xml() -> None:
    target = ProbeTarget(host="192.168.1.200", name="A")
    requests = [
        ProbeRequest(method=HttpMethod.GET, path="/ui"),
        ProbeRequest(method=HttpMethod.GET, path="/api/status"),
        ProbeRequest(method=HttpMethod.GET, path="/xml/status"),
    ]

    mapping = {
        f"{target.base_url()}/ui": ResponseSnapshot(
            status_code=200,
            headers={"Content-Type": "text/html; charset=utf-8"},
            body=b"<!doctype html><html><body>ok</body></html>",
        ),
        f"{target.base_url()}/api/status": ResponseSnapshot(
            status_code=200,
            headers={"Content-Type": "application/json"},
            body=b'{"ok": true}',
        ),
        f"{target.base_url()}/xml/status": ResponseSnapshot(
            status_code=200,
            headers={"Content-Type": "application/xml"},
            body=b'<?xml version="1.0" encoding="UTF-8"?><status>ok</status>',
        ),
    }

    service = LegrandDiscoveryService(transport=FakeTransport(mapping))
    report = service.discover(targets=[target], requests=requests, now=datetime(2026, 1, 1, tzinfo=UTC))

    kinds = {o.request.path: o.content_kind for o in report.observations}
    assert str(kinds["/ui"]) == "html"
    assert str(kinds["/api/status"]) == "json"
    assert str(kinds["/xml/status"]) == "xml"

