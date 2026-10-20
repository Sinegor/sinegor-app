"""Opaque credentials, Argon2id, encrypted TOTP and session-bound CSRF."""

import hashlib
import hmac
import secrets
import time

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, InvalidToken

HASHER = PasswordHasher()
DUMMY_HASH = HASHER.hash(secrets.token_urlsafe(32))


def secret_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_secret() -> str:
    return secrets.token_urlsafe(32)


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        return HASHER.verify(stored_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def matched_totp_step(encrypted: str, key: str, code: str, now: float) -> int | None:
    try:
        secret = Fernet(key.encode()).decrypt(encrypted.encode()).decode()
        totp = pyotp.TOTP(secret)
        step = int(now) // totp.interval
        matches = [
            candidate
            for candidate in (step - 1, step, step + 1)
            if hmac.compare_digest(totp.generate_otp(candidate), code)
        ]
        return max(matches) if matches else None
    except (InvalidToken, ValueError, TypeError):
        return None


def csrf_token(key: str, session_cookie: str, now: int | None = None) -> str:
    prefix = f"{int(time.time()) if now is None else now}.{new_secret()}"
    signature = hmac.new(
        key.encode(), f"{prefix}.{secret_hash(session_cookie)}".encode(), hashlib.sha256
    ).hexdigest()
    return f"{prefix}.{signature}"


def valid_csrf(token: str, key: str, session_cookie: str, ttl: int, now: int | None = None) -> bool:
    try:
        stamp, nonce, signature = token.split(".")
        age = (int(time.time()) if now is None else now) - int(stamp)
        prefix = f"{stamp}.{nonce}"
        expected = hmac.new(
            key.encode(), f"{prefix}.{secret_hash(session_cookie)}".encode(), hashlib.sha256
        ).hexdigest()
        return 0 <= age < ttl and len(nonce) == 43 and hmac.compare_digest(expected, signature)
    except (ValueError, TypeError):
        return False
