from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from condocharge.app.integrations.legrand.discovery.models import (
    ContentKind,
    ProbeObservation,
    ProtocolCandidate,
    ProtocolFingerprint,
)


@dataclass(frozen=True)
class FingerprintRule:
    candidate: ProtocolCandidate
    predicate: Callable[[ProbeObservation], bool]
    evidence: str
    weight: float


class ProtocolFingerprinter:
    def __init__(self, rules: Sequence[FingerprintRule] | None = None) -> None:
        self._rules = list(rules or self._default_rules())

    def fingerprint(self, observations: Sequence[ProbeObservation]) -> list[ProtocolFingerprint]:
        scores: dict[ProtocolCandidate, float] = {}
        evidence: dict[ProtocolCandidate, list[str]] = {}

        for obs in observations:
            for rule in self._rules:
                if rule.predicate(obs):
                    scores[rule.candidate] = scores.get(rule.candidate, 0.0) + rule.weight
                    evidence.setdefault(rule.candidate, []).append(rule.evidence)

        if not scores:
            return [ProtocolFingerprint(candidate=ProtocolCandidate.UNKNOWN, confidence=0.2, evidence=[])]

        max_score = max(scores.values())
        fingerprints: list[ProtocolFingerprint] = []
        for candidate, score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
            confidence = 0.2 if max_score == 0 else min(1.0, score / max_score)
            fingerprints.append(
                ProtocolFingerprint(candidate=candidate, confidence=confidence, evidence=evidence.get(candidate, []))
            )
        return fingerprints

    @staticmethod
    def _default_rules() -> list[FingerprintRule]:
        return [
            FingerprintRule(
                candidate=ProtocolCandidate.HTML_UI,
                predicate=lambda o: o.content_kind == ContentKind.HTML and (o.status_code or 0) >= 200,
                evidence="html_content_detected",
                weight=1.0,
            ),
            FingerprintRule(
                candidate=ProtocolCandidate.JSON_API,
                predicate=lambda o: o.content_kind == ContentKind.JSON and (o.status_code or 0) >= 200,
                evidence="json_content_detected",
                weight=1.2,
            ),
            FingerprintRule(
                candidate=ProtocolCandidate.XML_API,
                predicate=lambda o: o.content_kind == ContentKind.XML and (o.status_code or 0) >= 200,
                evidence="xml_content_detected",
                weight=1.1,
            ),
            FingerprintRule(
                candidate=ProtocolCandidate.REST,
                predicate=lambda o: o.status_code in {401, 403} and o.content_kind in {ContentKind.JSON, ContentKind.XML},
                evidence="api_style_auth_response_detected",
                weight=0.6,
            ),
        ]
