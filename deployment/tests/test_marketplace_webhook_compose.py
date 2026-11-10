"""Render shipped Compose variants to check marketplace delivery dispatch settings."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from pydantic import BaseModel, Field

COMPOSE_DIR = Path(__file__).resolve().parents[1] / "docker_compose"


class Service(BaseModel):
    environment: dict[str, str | None] = Field(default_factory=dict)


class Compose(BaseModel):
    services: dict[str, Service]


@pytest.mark.parametrize(
    "variant",
    [
        "docker-compose.yml",
        "docker-compose.prod.yml",
        "docker-compose.prod-no-letsencrypt.yml",
    ],
)
@pytest.mark.parametrize("lite", [False, True])
def test_webhook_dispatch_uses_deployment_backends(
    variant: str, lite: bool, tmp_path: Path
) -> None:
    for name in (variant, "docker-compose.onyx-lite.yml"):
        shutil.copyfile(COMPOSE_DIR / name, tmp_path / name)
    (tmp_path / ".env.nginx").touch()
    command = [
        "docker",
        "compose",
        "--env-file",
        "/dev/null",
        "--profile",
        "webhook",
        "-f",
        str(tmp_path / variant),
    ]
    if lite:
        command.extend(["-f", str(tmp_path / "docker-compose.onyx-lite.yml")])
    command.extend(["config", "--no-env-resolution", "--format", "json"])
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
        env={
            "PATH": os.environ["PATH"],
            "S3_AWS_ACCESS_KEY_ID": "compose-render-test-only",
            "S3_AWS_SECRET_ACCESS_KEY": "compose-render-test-only",
        },
    )
    config = Compose.model_validate_json(result.stdout)
    hook = config.services["webhook_server"].environment
    assert hook["POSTGRES_HOST"] == "relational_db"
    if lite:
        assert "cache" not in config.services and "background" not in config.services
        for key, value in {
            "DISABLE_VECTOR_DB": "true",
            "FILE_STORE_BACKEND": "postgres",
            "CACHE_BACKEND": "postgres",
            "AUTH_BACKEND": "postgres",
        }.items():
            assert hook[key] == config.services["api_server"].environment[key] == value
    else:
        assert "cache" in config.services and "background" in config.services
        assert (
            hook["REDIS_HOST"]
            == config.services["background"].environment["REDIS_HOST"]
            == "cache"
        )
