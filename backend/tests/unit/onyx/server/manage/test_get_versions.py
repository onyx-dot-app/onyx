"""Tests for the public /versions endpoint, with DockerHub mocked out."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from onyx.server.manage.get_state import DOCUMENT_INDEX_IMAGE, get_versions

_COMPOSE_TEMPLATE = (
    Path(__file__).resolve().parents[6]
    / "deployment"
    / "docker_compose"
    / "docker-compose.template.yml"
)


def _dockerhub_page(_url: str, timeout: int) -> MagicMock:  # noqa: ARG001
    response = MagicMock()
    page: dict[str, Any] = {
        "results": [
            {"name": "v3.1.0"},
            {"name": "v3.2.0"},
            {"name": "v3.3.0-beta.1"},
            {"name": "v3.3.0-beta.2"},
            {"name": "latest"},
        ],
        "next": None,
    }
    response.json.return_value = page
    return response


def test_versions_report_the_opensearch_index_image() -> None:
    with patch(
        "onyx.server.manage.get_state.requests.get", side_effect=_dockerhub_page
    ):
        versions = get_versions()

    assert versions.stable.onyx == "v3.2.0"
    assert versions.dev.onyx == "v3.3.0-beta.2"
    for container_versions in (versions.stable, versions.dev, versions.migration):
        assert container_versions.index == DOCUMENT_INDEX_IMAGE
        assert "vespa" not in container_versions.index


def test_index_image_matches_the_docker_compose_deployment() -> None:
    """The /versions index image must be the one docker compose deploys."""
    template = _COMPOSE_TEMPLATE.read_text()
    assert f"/{DOCUMENT_INDEX_IMAGE}\n" in template
