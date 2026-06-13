from __future__ import annotations

import base64
import hashlib
import hmac
import os
from datetime import UTC, datetime, timedelta
from typing import cast

import jwt
from pydantic import BaseModel


class TokenPayload(BaseModel):
    sub: str
    exp: int
    condominium_id: int
    role: str
    ver: int = 0


def hash_password(password: str) -> str:
    iterations = 260_000
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256${iterations}${salt_b64}${digest_b64}".format(
        iterations=iterations,
        salt_b64=base64.b64encode(salt).decode("ascii"),
        digest_b64=base64.b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        scheme, iterations_s, salt_b64, digest_b64 = password_hash.split("$", 3)
    except ValueError:
        return False
    if scheme != "pbkdf2_sha256":
        return False
    try:
        iterations = int(iterations_s)
        salt = base64.b64decode(salt_b64.encode("ascii"))
        expected = base64.b64decode(digest_b64.encode("ascii"))
    except Exception:
        return False
    computed = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(computed, expected)


def create_access_token(
    *,
    user_id: int,
    condominium_id: int,
    role: str,
    token_version: int,
    secret_key: str,
    algorithm: str,
    expires_minutes: int,
) -> str:
    expire = datetime.now(tz=UTC) + timedelta(minutes=expires_minutes)
    payload = {
        "sub": str(user_id),
        "condominium_id": condominium_id,
        "role": role,
        "ver": token_version,
        "exp": int(expire.timestamp()),
    }
    return cast(str, jwt.encode(payload, secret_key, algorithm=algorithm))


def decode_access_token(*, token: str, secret_key: str, algorithm: str) -> TokenPayload:
    data = jwt.decode(token, secret_key, algorithms=[algorithm])
    return TokenPayload.model_validate(data)
