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
    vision_provider: Literal["fake", "http"] = "fake"
    vision_api_url: str | None = None
    vision_api_key: SecretStr | None = None
    vision_model_name: str = "unconfigured"
    #: Leitor local de folhas (Ollama). Só aceita endereço da própria máquina
    #: ou da rede interna — ver `app.vision.sheet_reader.ensure_local_url`.
    #: Leitor de eventos do worker. "fake" inventa leitura (CI e demonstração);
    #: "ollama" lê de verdade, no endereço de `reader_url`.
    reader_provider: Literal["fake", "ollama"] = "fake"
    reader_url: str = "http://127.0.0.1:11434"
    reader_model: str = "qwen2.5vl:7b"
    auth_secret: SecretStr | None = None
    auth_token_ttl_seconds: int = Field(default=900, ge=60, le=86_400)
    #: Validade da sessão renovável, em segundos. Padrão de 30 dias.
    auth_refresh_ttl_seconds: int = Field(
        default=30 * 24 * 60 * 60, ge=3_600, le=365 * 24 * 60 * 60
    )
    #: Marca o cookie de sessão como `Secure`. Padrão verdadeiro: sem TLS o
    #: cookie viaja em texto puro. Só desligue para desenvolvimento local em
    #: http://localhost, onde o navegador não enviaria um cookie `Secure`.
    auth_cookie_secure: bool = True
    #: Mostra a área "Fichas" mesmo com o provedor de OCR falso. Existe para
    #: demonstração e para o teste E2E do fluxo de foto; em produção é
    #: recusado, porque o provedor falso inventa leituras.
    photo_sheets_demo: bool = False

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
        if self.runtime_role == "worker" and self.vision_provider == "http":
            required += ["vision_api_url", "vision_api_key"]
        if self.runtime_role == "worker" and self.reader_provider == "ollama":
            required.append("reader_url")
        missing = [name for name in required if not getattr(self, name)]
        if missing:
            raise ValueError(
                "Missing required production settings: " + ", ".join(missing)
            )

        # Um cookie de sessão sem `Secure` viaja em texto puro. Desligar isso
        # é legítimo em desenvolvimento local, onde não há TLS; em produção é
        # um erro de configuração que entregaria a sessão de qualquer usuário,
        # e falhar na inicialização é melhor do que descobrir depois.
        if self.photo_sheets_demo:
            raise ValueError(
                "photo_sheets_demo must stay disabled in production: the fake OCR "
                "provider invents readings"
            )

        # O leitor falso devolve sempre o mesmo caderno. Em produção isso
        # encheria a caixa de revisão de dado inventado, com a foto de verdade
        # ignorada — e alguém acabaria aprovando.
        if self.runtime_role == "worker" and self.reader_provider == "fake":
            raise ValueError(
                "reader_provider must not stay 'fake' in production: the fake "
                "reader invents readings instead of reading the photo"
            )

        if self.runtime_role == "api" and not self.auth_cookie_secure:
            raise ValueError(
                "auth_cookie_secure must stay enabled in production: without it "
                "the session cookie travels in clear text"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


def photo_sheets_enabled(settings: Settings) -> bool:
    """Se a área de fichas por foto deve aparecer nesta instalação."""
    return settings.vision_provider == "http" or settings.photo_sheets_demo
