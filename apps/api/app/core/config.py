from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Server-only configuration for ingestion infrastructure."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    runtime_role: Literal["api", "worker"] = "api"
    postgres_url: str | None = None
    redis_url: str | None = None
    minio_url: str | None = None
    minio_access_key: str | None = None
    minio_secret_key: str | None = None
    minio_bucket: str = "sheets"
    max_upload_bytes: int = Field(default=15_000_000, ge=1)
    auth_secret: SecretStr | None = None
    auth_token_ttl_seconds: int = Field(default=900, ge=60, le=86_400)

    @field_validator("auth_secret")
    @classmethod
    def require_secure_auth_secret(
        cls, secret: SecretStr | None, info: ValidationInfo
    ) -> SecretStr | None:
        if info.data.get("runtime_role") != "api":
            return secret
        if secret is not None and len(secret.get_secret_value().encode("utf-8")) < 32:
            raise ValueError("AUTH_SECRET must contain at least 32 bytes")
        return secret

    @model_validator(mode="after")
    def require_production_infrastructure(self) -> "Settings":
        if self.environment != "production":
            return self

        required = [
            "postgres_url",
            "redis_url",
            "minio_url",
            "minio_access_key",
            "minio_secret_key",
        ]
        if self.runtime_role == "api":
            required.append("auth_secret")
        missing = [name for name in required if not getattr(self, name)]
        if missing:
            raise ValueError(
                "Missing required production settings: " + ", ".join(missing)
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
