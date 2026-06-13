from __future__ import annotations

import re
from functools import lru_cache

from pydantic import AnyUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CONDOCHARGE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = Field(default="development")
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000)

    database_url: str = Field(default="sqlite+pysqlite:///./condocharge_dev.sqlite3")

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

    legrand_username: str = Field(default="")
    legrand_password: str = Field(default="")

    @property
    def normalized_env(self) -> str:
        return self.env.strip().lower()

    @property
    def requires_secure_runtime(self) -> bool:
        return self.normalized_env in {"pilot", "production"}

    @property
    def cors_origin_strings(self) -> list[str]:
        return [str(origin).strip().rstrip("/") for origin in self.cors_origins]

    def validate_runtime_settings(self) -> None:
        public_url = self.public_url.strip().rstrip("/")

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

        if not self.requires_secure_runtime:
            return

        secret = self.jwt_secret_key.strip()
        if not secret or secret in {"change-me", "changeme", "default", "secret"}:
            raise RuntimeError(
                "Unsafe CONDOCHARGE_JWT_SECRET_KEY for pilot/production. "
                "Set a strong non-default secret before startup."
            )

        cors_values = self.cors_origin_strings
        if "*" in cors_values:
            raise RuntimeError("Wildcard CONDOCHARGE_CORS_ORIGINS is not allowed in pilot/production.")


@lru_cache
def get_settings() -> Settings:
    return Settings()


_LAN_PUBLIC_URL_RE = re.compile(r"^http://192\.168\.\d{1,3}\.\d{1,3}(?::\d+)?(?:/.*)?$", re.IGNORECASE)


def _is_allowed_lan_public_url(public_url: str) -> bool:
    return bool(_LAN_PUBLIC_URL_RE.match(public_url.strip()))
