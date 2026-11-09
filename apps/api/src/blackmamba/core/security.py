"""Password hashing (argon2), JWTs, TOTP and field-level encryption."""

import base64
import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, InvalidToken

from blackmamba.core.config import Settings, get_settings

_hasher = PasswordHasher()

TokenType = Literal["access", "refresh"]


# ------------------------------------------------------------------ passwords
def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


# A real argon2 hash used to equalise timing when the user does not exist.
DUMMY_PASSWORD_HASH = hash_password("timing-equaliser-not-a-real-password")


# ------------------------------------------------------------------ JWT
@dataclass(frozen=True)
class TokenClaims:
    user_id: uuid.UUID
    token_type: TokenType
    version: int


class TokenError(Exception):
    pass


def create_token(
    user_id: uuid.UUID,
    token_type: TokenType,
    version: int,
    settings: Settings | None = None,
) -> str:
    settings = settings or get_settings()
    now = datetime.now(UTC)
    lifetime = (
        timedelta(minutes=settings.access_token_minutes)
        if token_type == "access"  # nosec B105
        else timedelta(days=settings.refresh_token_days)
    )
    payload = {
        "sub": str(user_id),
        "typ": token_type,
        "ver": version,
        "iat": now,
        "exp": now + lifetime,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(
        payload, settings.secret_key.get_secret_value(), algorithm=settings.jwt_algorithm
    )


def decode_token(
    token: str, expected_type: TokenType, settings: Settings | None = None
) -> TokenClaims:
    settings = settings or get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "typ", "exp", "ver"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenError("invalid token") from exc
    if payload.get("typ") != expected_type:
        raise TokenError("wrong token type")
    try:
        return TokenClaims(
            user_id=uuid.UUID(str(payload["sub"])),
            token_type=expected_type,
            version=int(payload["ver"]),
        )
    except (ValueError, TypeError) as exc:
        raise TokenError("malformed token") from exc


# ------------------------------------------------------------------ TOTP
TOTP_ISSUER = "BLACK MAMBA"


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=TOTP_ISSUER)


def verify_totp(secret: str, code: str) -> bool:
    code = code.strip().replace(" ", "")
    if not code.isdigit() or len(code) != 6:
        return False
    return bool(pyotp.TOTP(secret).verify(code, valid_window=1))


# ------------------------------------------------------------------ field encryption
def _fernet(settings: Settings | None = None) -> Fernet:
    settings = settings or get_settings()
    if settings.field_encryption_key is not None:
        return Fernet(settings.field_encryption_key.get_secret_value().encode())
    digest = hashlib.sha256(
        b"blackmamba-field-encryption:" + settings.secret_key.get_secret_value().encode()
    ).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_field(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_field(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("cannot decrypt field (wrong FIELD_ENCRYPTION_KEY?)") from exc
