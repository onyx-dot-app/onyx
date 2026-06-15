from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
COMPOSE_PATH = REPO_ROOT / "deployment" / "docker_compose" / "docker-compose.yml"
PROD_COMPOSE_PATH = (
    REPO_ROOT / "deployment" / "docker_compose" / "docker-compose.prod.yml"
)
ENV_TEMPLATE_PATH = REPO_ROOT / "deployment" / "docker_compose" / "env.template"
PROD_ENV_TEMPLATE_PATH = (
    REPO_ROOT / "deployment" / "docker_compose" / "env.prod.template"
)


def _load_compose(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as compose_file:
        loaded = yaml.safe_load(compose_file)
    assert isinstance(loaded, dict)
    return loaded


def _assert_compose_runs_gateway(path: Path) -> None:
    compose = _load_compose(path)
    services = compose["services"]

    gateway = services["search_gateway"]
    assert "7777" in gateway["command"]
    assert "onyx.search_gateway.server:app" in gateway["command"]
    assert "ports" not in gateway
    assert gateway["restart"] == "unless-stopped"

    api_depends_on = services["api_server"]["depends_on"]
    if isinstance(api_depends_on, dict):
        assert api_depends_on["search_gateway"]["condition"] == "service_healthy"
    else:
        assert "search_gateway" in api_depends_on


def test_full_compose_runs_glomi_search_gateway_internally() -> None:
    _assert_compose_runs_gateway(COMPOSE_PATH)


def test_prod_compose_runs_glomi_search_gateway_internally() -> None:
    _assert_compose_runs_gateway(PROD_COMPOSE_PATH)


def test_env_template_points_glomi_provider_at_compose_gateway() -> None:
    env_template = ENV_TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "GLOMI_DEFAULT_WEB_SEARCH_ENABLED=true" in env_template
    assert (
        "GLOMI_DEFAULT_WEB_SEARCH_API_BASE=http://search_gateway:7777"
        in env_template
    )
    assert "GLOMI_SEARCH_GATEWAY_API_KEY=" in env_template
    assert "TAVILY_API_KEY=" in env_template


def test_prod_env_template_points_glomi_provider_at_compose_gateway() -> None:
    env_template = PROD_ENV_TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "GLOMI_DEFAULT_WEB_SEARCH_ENABLED=true" in env_template
    assert (
        "GLOMI_DEFAULT_WEB_SEARCH_API_BASE=http://search_gateway:7777"
        in env_template
    )
    assert "GLOMI_SEARCH_GATEWAY_API_KEY=" in env_template
    assert "TAVILY_API_KEY=" in env_template
