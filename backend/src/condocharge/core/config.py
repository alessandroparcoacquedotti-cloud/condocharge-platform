from __future__ import annotations

import re
from functools import lru_cache

from pydantic import AnyUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_PRODUCTION_CORS_ORIGINS = (
    "https://shimmering-quietude-production.up.railway.app",
)
DEFAULT_DEV_DATABASE_URL = "sqlite+pysqlite:///./condocharge_dev.sqlite3"
_KNOWN_WEAK_JWT_SECRETS = {
    "",
    "change-me",
    "changeme",
    "default",
    "secret",
    "jwt",
    "jwt-secret",
    "jwtsecret",
    "token",
    "password",
    "condocharge",
    "condocharge-secret",
    "condocharge-jwt-secret",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CONDOCHARGE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    deployment: str = Field(default="demo")
    env: str = Field(default="development")
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000)

    database_url: str = Field(default=DEFAULT_DEV_DATABASE_URL)

    jwt_secret_key: str = Field(default="change-me")
    jwt_algorithm: str = Field(default="HS256")
    jwt_access_token_expires_minutes: int = Field(default=30)

    cors_origins: list[AnyUrl] = Field(default_factory=list)
    public_url: str = Field(default="")
    lan_mode: bool = Field(default=False)
    email_enabled: bool = Field(default=False)
    email_from: str = Field(default="noreply@condocharge.local")
    smtp_host: str = Field(default="")
    smtp_port: int = Field(default=587)
    smtp_username: str = Field(default="")
    smtp_password: str = Field(default="")
    smtp_use_tls: bool = Field(default=True)
    notifications_enabled: bool = Field(default=False)
    notification_poll_interval_seconds: int = Field(default=30)
    notification_recency_minutes: int = Field(default=30)
    notification_station_cooldown_minutes: int = Field(default=15)
    notification_resident_cooldown_minutes: int = Field(default=5)
    queue_assignment_start_hour: int = Field(default=8)
    queue_assignment_end_hour: int = Field(default=22)
    queue_reservation_grace_minutes: int = Field(default=30)
    queue_completion_reminder_minutes: int = Field(default=30)
    queue_completion_final_reminder_minutes: int = Field(default=60)
    telegram_bot_token: str = Field(default="")
    telegram_bot_username: str = Field(default="")
    telegram_webhook_secret: str = Field(default="")
    telegram_link_token_ttl_minutes: int = Field(default=30)
    telegram_request_timeout_seconds: int = Field(default=10)
    telegram_agent_offline_threshold_seconds: int = Field(default=180)

    legrand_username: str = Field(default="")
    legrand_password: str = Field(default="")

    agent_enabled: bool = Field(default=False)
    agent_token_current: str = Field(default="")
    agent_token_next: str = Field(default="")
    agent_allowed_condominium_ids: str = Field(default="")
    agent_occupancy_source: str = Field(default="live")
    agent_stale_after_seconds: int = Field(default=90)

    @property
    def normalized_agent_occupancy_source(self) -> str:
        value = self.agent_occupancy_source.strip().lower()
        return value if value in {"live", "db", "live_only"} else "live"

    @property
    def agent_allowed_condominium_id_set(self) -> set[int]:
        raw = self.agent_allowed_condominium_ids.strip()
        if not raw:
            return set()
        out: set[int] = set()
        for part in raw.replace(";", ",").split(","):
            p = part.strip()
            if not p:
                continue
            try:
                out.add(int(p))
            except ValueError:
                continue
        return out

    @property
    def normalized_env(self) -> str:
        return self.env.strip().lower()

    @property
    def normalized_deployment(self) -> str:
        return self.deployment.strip().lower()

    @property
    def requires_production_deployment_guards(self) -> bool:
        return self.normalized_deployment == "production"

    @property
    def requires_secure_runtime(self) -> bool:
        return self.normalized_env in {"pilot", "production"}

    @property
    def cors_origin_strings(self) -> list[str]:
        return [str(origin).strip().rstrip("/") for origin in self.cors_origins]

    @property
    def effective_cors_origin_strings(self) -> list[str]:
        configured = self.cors_origin_strings
        if configured:
            return configured
        if self.requires_secure_runtime:
            return list(DEFAULT_PRODUCTION_CORS_ORIGINS)
        return []

    def validate_runtime_settings(self) -> None:
        public_url = self.public_url.strip().rstrip("/")
        database_url = self.database_url.strip()
        database_url_was_configured = "database_url" in self.model_fields_set

        if self.requires_production_deployment_guards:
            if not database_url_was_configured or not database_url:
                raise RuntimeError(
                    "CONDOCHARGE_DATABASE_URL must be explicitly set for CONDOCHARGE_DEPLOYMENT=production."
                )
            lowered_database_url = database_url.lower()
            if "condocharge_dev.sqlite3" in lowered_database_url:
                raise RuntimeError(
                    "CONDOCHARGE_DATABASE_URL cannot reference condocharge_dev.sqlite3 in production deployment."
                )
            if "demo.sqlite3" in lowered_database_url:
                raise RuntimeError(
                    "CONDOCHARGE_DATABASE_URL cannot reference demo.sqlite3 in production deployment."
                )

        if public_url:
            if self.requires_secure_runtime and not public_url.lower().startswith("https://"):
                raise RuntimeError("CONDOCHARGE_PUBLIC_URL must use https:// in pilot/production.")

            if not self.requires_secure_runtime:
                if not self.lan_mode:
                    raise RuntimeError(
                        "CONDOCHARGE_ENV must be pilot or production when CONDOCHARGE_PUBLIC_URL is configured. "
                        "Set CONDOCHARGE_LAN_MODE=true only for explicit LAN mode."
                    )
                if not _is_allowed_lan_public_url(public_url):
                    raise RuntimeError(
                        "Explicit LAN mode only allows CONDOCHARGE_PUBLIC_URL values starting with "
                        "http://192.168.x.x"
                    )

        secret = self.jwt_secret_key.strip()
        if self.requires_production_deployment_guards:
            _validate_jwt_secret(secret)

        if not self.requires_secure_runtime:
            return

        _validate_jwt_secret(secret)

        cors_values = self.effective_cors_origin_strings
        if "*" in cors_values:
            raise RuntimeError("Wildcard CONDOCHARGE_CORS_ORIGINS is not allowed in pilot/production.")


@lru_cache
def get_settings() -> Settings:
    return Settings()


_LAN_PUBLIC_URL_RE = re.compile(r"^http://192\.168\.\d{1,3}\.\d{1,3}(?::\d+)?(?:/.*)?$", re.IGNORECASE)


def _is_allowed_lan_public_url(public_url: str) -> bool:
    return bool(_LAN_PUBLIC_URL_RE.match(public_url.strip()))


def _validate_jwt_secret(secret: str) -> None:
    normalized = secret.strip()
    lowered = normalized.lower()

    if not normalized:
        raise RuntimeError(
            "Unsafe CONDOCHARGE_JWT_SECRET_KEY for pilot/production. Secret cannot be empty and must be at least 32 bytes."
        )

    if lowered in _KNOWN_WEAK_JWT_SECRETS:
        raise RuntimeError(
            "Unsafe CONDOCHARGE_JWT_SECRET_KEY for pilot/production. Rejecting default or obvious secrets."
        )

    if len(normalized.encode("utf-8")) < 32:
        raise RuntimeError(
            "Unsafe CONDOCHARGE_JWT_SECRET_KEY for pilot/production. Secret must be at least 32 bytes."
        )

    if _looks_like_obvious_secret(lowered):
        raise RuntimeError(
            "Unsafe CONDOCHARGE_JWT_SECRET_KEY for pilot/production. Rejecting obvious low-entropy secrets."
        )


def _looks_like_obvious_secret(lowered_secret: str) -> bool:
    if re.fullmatch(r"(.)\1{7,}", lowered_secret):
        return True
    return re.fullmatch(
        r"(?:1234|abcd|password|secret|token|jwt|condocharge|qwer|asdf|zxcv)[-_0-9a-z]*",
        lowered_secret,
    ) is not None
