import json
import os
from pathlib import Path
import subprocess


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_materialized_compose_configuration_keeps_auth_secret_out_of_worker() -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "POSTGRES_PASSWORD": "test-only-database-password",
            "POSTGRES_URL": "postgresql+asyncpg://ingestion:test@db/ingestion",
            "MINIO_ACCESS_KEY": "test-only-access-key",
            "MINIO_SECRET_KEY": "test-only-object-password",
            "AUTH_SECRET": "test-only-secret-with-at-least-32-bytes",
        }
    )

    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(REPOSITORY_ROOT / "infra" / "docker-compose.yml"),
            "config",
            "--format",
            "json",
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    configuration = json.loads(result.stdout)

    assert "AUTH_SECRET" in configuration["services"]["api"]["environment"]
    assert "AUTH_SECRET" not in configuration["services"]["worker"]["environment"]


def test_local_environment_files_are_ignored_except_for_safe_examples() -> None:
    ignored = subprocess.run(
        ["git", "check-ignore", ".env", ".env.local", ".env.test"],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    example = subprocess.run(
        ["git", "check-ignore", ".env.example"],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert ignored.returncode == 0
    assert set(ignored.stdout.splitlines()) == {".env", ".env.local", ".env.test"}
    assert example.returncode == 1
