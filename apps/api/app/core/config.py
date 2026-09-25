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
    #: Leitor local de folhas (Ollama). Só aceita endereço da própria máquina
    #: ou da rede interna — ver `app.core.local_url.ensure_local_url`.
    #: Leitor de eventos do worker. "fake" inventa leitura (CI e demonstração);
    #: "ollama" lê de verdade, no endereço de `reader_url`.
    reader_provider: Literal["fake", "ollama"] = "fake"
    reader_url: str = "http://127.0.0.1:11434"
    reader_model: str = "qwen2.5vl:7b"
    #: Transcritor da gravação de voz (whisper.cpp). Mesma regra do leitor de
    #: fotos: "fake" inventa a fala (CI e demonstração), "whisper" transcreve
    #: de verdade no endereço de `audio_url`, que só pode ser da própria
    #: máquina ou da rede interna. A porta padrão é 8081 porque a 8080 é a do
    #: app.
    audio_provider: Literal["fake", "whisper"] = "fake"
    audio_url: str = "http://127.0.0.1:8081"
    #: Informativo: vai na versão da leitura, para comparar modelos.
    audio_model: str = "ggml-large-v3-turbo-q5_0"
    audio_language: str = "pt"
    #: Gravação mais longa que isto não é transcrita: prenderia a GPU.
    audio_max_seconds: int = Field(default=300, ge=10, le=3_600)
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
        if self.runtime_role == "worker" and self.reader_provider == "ollama":
            required.append("reader_url")
        if self.runtime_role == "worker" and self.audio_provider == "whisper":
            required.append("audio_url")
        missing = [name for name in required if not getattr(self, name)]
        if missing:
            raise ValueError(
                "Missing required production settings: " + ", ".join(missing)
            )

        # O leitor falso devolve sempre o mesmo caderno. Em produção isso
        # encheria a caixa de revisão de dado inventado, com a foto de verdade
        # ignorada — e alguém acabaria aprovando.
        if self.runtime_role == "worker" and self.reader_provider == "fake":
            raise ValueError(
                "reader_provider must not stay 'fake' in production: the fake "
                "reader invents readings instead of reading the photo"
            )

        # O mesmo vale para a fala: o transcritor falso devolve sempre a mesma
        # frase, e a gravação de verdade ficaria ignorada.
        if self.runtime_role == "worker" and self.audio_provider == "fake":
            raise ValueError(
                "audio_provider must not stay 'fake' in production: the fake "
                "transcriber invents speech instead of listening to the recording"
            )

        # Um cookie de sessão sem `Secure` viaja em texto puro. Desligar isso
        # é legítimo em desenvolvimento local, onde não há TLS; em produção é
        # um erro de configuração que entregaria a sessão de qualquer usuário,
        # e falhar na inicialização é melhor do que descobrir depois.
        if self.runtime_role == "api" and not self.auth_cookie_secure:
            raise ValueError(
                "auth_cookie_secure must stay enabled in production: without it "
                "the session cookie travels in clear text"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
