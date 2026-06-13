from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class HttpMethod(StrEnum):
    GET = "GET"
    HEAD = "HEAD"


class ContentKind(StrEnum):
    UNKNOWN = "unknown"
    HTML = "html"
    JSON = "json"
    XML = "xml"
    TEXT = "text"
    BINARY = "binary"


class ProbeRequest(BaseModel):
    method: HttpMethod = HttpMethod.GET
    path: str
    headers: dict[str, str] = Field(default_factory=dict)


class ProbeTarget(BaseModel):
    host: str
    name: str | None = None
    scheme: str = "http"
    port: int | None = None

    def base_url(self) -> str:
        port = f":{self.port}" if self.port is not None else ""
        return f"{self.scheme}://{self.host}{port}"


class ResponseSnapshot(BaseModel):
    status_code: int
    headers: dict[str, str] = Field(default_factory=dict)
    body: bytes = b""


class ProbeObservation(BaseModel):
    target: ProbeTarget
    request: ProbeRequest
    url: str

    status_code: int | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    content_type: str | None = None
    content_kind: ContentKind = ContentKind.UNKNOWN
    content_length: int | None = None
    is_redirect: bool = False
    redirect_location: str | None = None

    fingerprints: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    observed_at: datetime


class ProtocolCandidate(StrEnum):
    UNKNOWN = "unknown"
    REST = "rest"
    JSON_API = "json_api"
    XML_API = "xml_api"
    HTML_UI = "html_ui"


class ProtocolFingerprint(BaseModel):
    candidate: ProtocolCandidate
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)


class DiscoverySummary(BaseModel):
    target: ProbeTarget
    reachable: bool
    top_fingerprints: list[ProtocolFingerprint] = Field(default_factory=list)
    endpoints_with_content: int
    redirects: int


class LegrandDiscoveryReport(BaseModel):
    generated_at: datetime
    targets: list[DiscoverySummary] = Field(default_factory=list)
    observations: list[ProbeObservation] = Field(default_factory=list)
