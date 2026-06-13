from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime, timezone

from condocharge.app.integrations.legrand.discovery.fingerprinting import ProtocolFingerprinter
from condocharge.app.integrations.legrand.discovery.inspection import (
    content_length_from_headers,
    content_type_from_headers,
    is_redirect,
    redirect_location,
    sniff_content_kind,
)
from condocharge.app.integrations.legrand.discovery.models import (
    DiscoverySummary,
    LegrandDiscoveryReport,
    ProbeObservation,
    ProbeRequest,
    ProbeTarget,
)
from condocharge.app.integrations.legrand.discovery.transport import DiscoveryTransport


class LegrandDiscoveryService:
    def __init__(
        self,
        *,
        transport: DiscoveryTransport,
        fingerprinter: ProtocolFingerprinter | None = None,
    ) -> None:
        self._transport = transport
        self._fingerprinter = fingerprinter or ProtocolFingerprinter()

    def discover(
        self,
        *,
        targets: Sequence[ProbeTarget],
        requests: Sequence[ProbeRequest],
        now: datetime | None = None,
    ) -> LegrandDiscoveryReport:
        generated_at = now or datetime.now(tz=timezone.utc)
        observations: list[ProbeObservation] = []

        for target in targets:
            observations.extend(self._probe_target(target=target, requests=requests, observed_at=generated_at))

        summaries = [self._summarize_target(target, observations) for target in targets]
        return LegrandDiscoveryReport(generated_at=generated_at, targets=summaries, observations=observations)

    def _probe_target(
        self,
        *,
        target: ProbeTarget,
        requests: Sequence[ProbeRequest],
        observed_at: datetime,
    ) -> list[ProbeObservation]:
        results: list[ProbeObservation] = []
        for req in requests:
            url = f"{target.base_url()}{req.path}"
            obs = ProbeObservation(target=target, request=req, url=url, observed_at=observed_at)
            try:
                snapshot = self._transport.fetch(target=target, request=req)
                obs.status_code = snapshot.status_code
                obs.headers = snapshot.headers
                obs.content_type = content_type_from_headers(snapshot.headers)
                obs.content_length = content_length_from_headers(snapshot.headers)
                obs.is_redirect = is_redirect(snapshot.status_code)
                obs.redirect_location = redirect_location(snapshot.headers)
                obs.content_kind = sniff_content_kind(snapshot)
            except Exception as e:
                obs.notes.append(type(e).__name__)
            results.append(obs)
        return results

    def _summarize_target(self, target: ProbeTarget, observations: Sequence[ProbeObservation]) -> DiscoverySummary:
        related = [o for o in observations if o.target.host == target.host and o.target.port == target.port]
        reachable = any((o.status_code or 0) > 0 for o in related)
        redirects = sum(1 for o in related if o.is_redirect)
        endpoints_with_content = sum(1 for o in related if (o.content_length or 0) > 0 or o.content_type is not None)
        top_fingerprints = self._fingerprinter.fingerprint(related) if related else []
        return DiscoverySummary(
            target=target,
            reachable=reachable,
            top_fingerprints=top_fingerprints[:3],
            endpoints_with_content=endpoints_with_content,
            redirects=redirects,
        )


def build_probe_requests(*, paths: Iterable[str]) -> list[ProbeRequest]:
    return [ProbeRequest(path=p) for p in paths]
