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
