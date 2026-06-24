from __future__ import annotations

import pytest

from condocharge.core.config import Settings


def _pilot_settings(secret: str) -> Settings:
    return Settings(
        env="pilot",
        deployment="pilot",
        jwt_secret_key=secret,
    )


def test_validate_runtime_settings_accepts_valid_jwt_secret() -> None:
    settings = _pilot_settings("7b4f4a0c7d8e9f001122334455667788")
    settings.validate_runtime_settings()


@pytest.mark.parametrize(
    ("secret", "expected_message"),
    [
        ("", "cannot be empty"),
        ("short-secret", "at least 32 bytes"),
        ("change-me", "default or obvious secrets"),
        ("secretsecretsecretsecretsecretsecret", "obvious"),
    ],
)
def test_validate_runtime_settings_rejects_weak_jwt_secrets(secret: str, expected_message: str) -> None:
    settings = _pilot_settings(secret)
    with pytest.raises(RuntimeError, match=expected_message):
        settings.validate_runtime_settings()
