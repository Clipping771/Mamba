"""Application settings, loaded from environment variables / .env (pydantic-settings)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root .env (two levels above apps/api) is used when running outside Docker.
_API_DIR = Path(__file__).resolve().parents[3]
_ENV_FILES = (_API_DIR.parent.parent / ".env", _API_DIR / ".env")

# Dev placeholder; the production guard below rejects it.
_DEV_SECRET = "change-me-dev-only"  # noqa: S105  # nosec B105


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "BLACK MAMBA"
    app_env: Literal["development", "test", "production"] = "development"
    debug: bool = False
    cors_origins: list[str] = ["http://localhost:3000"]

    # ---- Auth (FR-1)
    secret_key: SecretStr = Field(default=SecretStr(_DEV_SECRET))
    jwt_algorithm: Literal["HS256"] = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    # Fernet key for field-level encryption (TOTP secrets, victim PII).
    # Derived from SECRET_KEY when unset (dev only; required in production).
    field_encryption_key: SecretStr | None = None
    login_rate_limit: int = 5  # attempts per window per IP+email
    login_rate_limit_ip: int = 30  # attempts per window per IP
    login_rate_window_seconds: int = 300
    rate_limit_backend: Literal["memory", "redis"] = "redis"
    min_password_length: int = 12
    invite_valid_days: int = 7
    password_reset_valid_minutes: int = 60

    # ---- SaaS / email
    # Base URL of the web app, used to build invite / reset links.
    public_web_url: str = "http://localhost:3000"
    smtp_host: str | None = None  # unset = email disabled (links returned to admins only)
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str = "BLACK MAMBA <no-reply@localhost>"
    smtp_starttls: bool = True

    # ---- Database
    database_url: str = "postgresql+asyncpg://blackmamba:blackmamba@localhost:5432/blackmamba"
    db_echo: bool = False
    db_pool_size: int = 5

    # ---- Queue
    redis_url: str = "redis://localhost:6379/0"

    # ---- Evidence storage (FR-3)
    storage_backend: Literal["s3", "local", "memory"] = "s3"
    local_storage_path: Path = Path("./var/evidence")
    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "blackmamba"
    s3_secret_key: SecretStr = Field(default=SecretStr(_DEV_SECRET))
    s3_bucket: str = "evidence"
    s3_region: str = "us-east-1"
    max_upload_mb: int = 50

    # ---- Archiver (FR-4)
    archive_timeout_seconds: int = 60
    # Only for tests/local fixtures. SSRF protection: never enable in production.
    archive_allow_private_hosts: bool = False

    # ---- ARCHIVIST agent (FR-10)
    llm_provider: Literal["anthropic", "ollama", "fake"] = "fake"
    llm_model: str = "claude-opus-5-5"
    llm_api_key: SecretStr | None = None
    llm_base_url: str | None = None  # e.g. http://localhost:11434 for Ollama
    llm_timeout_seconds: int = 120

    @model_validator(mode="after")
    def _production_guards(self) -> Self:
        if self.app_env == "production":
            secret = self.secret_key.get_secret_value()
            if secret == _DEV_SECRET or len(secret) < 32:
                raise ValueError("SECRET_KEY must be set to a strong value (>=32 chars)")
            if self.field_encryption_key is None:
                raise ValueError("FIELD_ENCRYPTION_KEY must be set in production")
            if self.archive_allow_private_hosts:
                raise ValueError("ARCHIVE_ALLOW_PRIVATE_HOSTS must be false in production")
            if self.storage_backend != "s3":
                raise ValueError("STORAGE_BACKEND must be s3 in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
