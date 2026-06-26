from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from condocharge.schemas.api import AgentStatusResponse


class SystemHealthResponse(BaseModel):
    server_time: datetime
    backend_ok: bool
    database_ok: bool
    railway_dns_ok: bool
    telegram_configured: bool
    push_configured: bool
    push_active_subscriptions: int
    agent_status: AgentStatusResponse
