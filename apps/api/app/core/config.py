from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Server-only configuration for ingestion infrastructure."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    postgres_url: str | None = None
    redis_url: str | None = None
    minio_url: str | None = None
    minio_access_key: str | None = None
    minio_secret_key: str | None = None

    @model_validator(mode="after")
    def require_production_infrastructure(self) -> "Settings":
        if self.environment != "production":
            return self

        required = (
            "postgres_url",
            "redis_url",
            "minio_url",
            "minio_access_key",
            "minio_secret_key",
        )
        missing = [name for name in required if not getattr(self, name)]
        if missing:
            raise ValueError(
                "Missing required production settings: " + ", ".join(missing)
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
