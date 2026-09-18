from pathlib import Path
import re


def _repository_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / ".gitignore").is_file() and (candidate / "infra" / "docker-compose.yml").is_file():
            return candidate
    raise RuntimeError("repository root not found")


def _service_block(compose_source: str, service: str) -> str:
    match = re.search(
        rf"^  {re.escape(service)}:\n(?P<body>.*?)(?=^  [a-z][\w-]*:|^networks:)",
        compose_source,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match, f"service {service!r} was not found in docker-compose.yml"
    return match.group("body")


def test_compose_declares_auth_secret_only_for_api() -> None:
    compose_source = (_repository_root() / "infra" / "docker-compose.yml").read_text()

    assert "AUTH_SECRET" in _service_block(compose_source, "api")
    assert "AUTH_SECRET" not in _service_block(compose_source, "worker")


def test_gitignore_excludes_local_environment_files_except_safe_example() -> None:
    rules = set((_repository_root() / ".gitignore").read_text().splitlines())

    assert {".env", ".env.*", "!.env.example"}.issubset(rules)


def test_production_refuses_an_insecure_session_cookie() -> None:
    """Desligar `Secure` em produção entregaria a sessão de qualquer usuário."""
    import pytest
    from pydantic import ValidationError

    from app.core.config import Settings

    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            runtime_role="api",
            postgres_url="postgresql+asyncpg://u:p@db:5432/x",
            redis_url="redis://redis:6379/0",
            minio_url="http://minio:9000",
            minio_access_key="a" * 12,
            minio_secret_key="b" * 12,
            auth_secret="c" * 40,
            auth_cookie_secure=False,
        )


def test_development_may_disable_the_secure_cookie() -> None:
    """Em http://localhost o navegador não enviaria um cookie `Secure`."""
    from app.core.config import Settings

    settings = Settings(environment="development", auth_cookie_secure=False)
    assert settings.auth_cookie_secure is False


def _nginx_config() -> str:
    return (_repository_root() / "infra" / "nginx.web.conf").read_text(encoding="utf-8")


def _api_dockerfile() -> str:
    return (_repository_root() / "infra" / "Dockerfile.api").read_text(encoding="utf-8")


def test_nginx_sets_the_security_headers_the_browser_needs() -> None:
    """Exposta na internet, a aplicação depende do navegador para recusar o
    que ela nunca faz."""
    config = _nginx_config()

    for header in (
        "Content-Security-Policy",
        "X-Content-Type-Options",
        "X-Frame-Options",
        "Referrer-Policy",
        "Permissions-Policy",
    ):
        assert f"add_header {header}" in config, header


def test_csp_blocks_third_party_scripts_and_framing() -> None:
    config = _nginx_config()

    assert "default-src 'self'" in config
    assert "script-src 'self'" in config
    # Nenhuma página deve ser embutida em outro site: as ações mudam dados do
    # rebanho e seriam alvo de clickjacking.
    assert "frame-ancestors 'none'" in config
    assert 'X-Frame-Options "DENY"' in config
    assert "object-src 'none'" in config


def test_hsts_stays_disabled_until_there_is_tls() -> None:
    """Habilitar HSTS sem certificado torna o site inacessível pelo max-age."""
    config = _nginx_config()

    for line in config.splitlines():
        if "Strict-Transport-Security" in line:
            assert line.strip().startswith("#"), line


def test_api_reads_forwarded_headers_from_trusted_sources_only() -> None:
    """Sem `--proxy-headers` o limite de login por origem seria inútil atrás do
    proxy; com `*` seria burlável, porque a porta 8000 é publicada."""
    dockerfile = _api_dockerfile()

    assert "--proxy-headers" in dockerfile
    assert "--forwarded-allow-ips" in dockerfile
    assert 'FORWARDED_ALLOW_IPS="*"' not in dockerfile
