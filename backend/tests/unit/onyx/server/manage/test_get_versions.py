"""Tests for the public /versions endpoint, with DockerHub mocked out."""

import threading
import traceback
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage import get_state
from onyx.server.manage.get_state import DOCUMENT_INDEX_IMAGE, get_versions

_COMPOSE_TEMPLATE = (
    Path(__file__).resolve().parents[6]
    / "deployment"
    / "docker_compose"
    / "docker-compose.template.yml"
)


@pytest.fixture(autouse=True)
def _reset_versions_cache() -> Generator[None, None, None]:
    get_state._VERSIONS_CACHE.clear()
    get_state._LAST_GOOD_VERSIONS = None
    get_state._LAST_VERSIONS_FAILURE_AT = None
    yield
    get_state._VERSIONS_CACHE.clear()
    get_state._LAST_GOOD_VERSIONS = None
    get_state._LAST_VERSIONS_FAILURE_AT = None


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


def test_versions_are_cached_across_calls() -> None:
    with patch(
        "onyx.server.manage.get_state.requests.get", side_effect=_dockerhub_page
    ) as mock_get:
        first = get_versions()
        second = get_versions()

    assert first == second
    # One page per repo, fetched once.
    assert mock_get.call_count == len(get_state._DOCKERHUB_REPOS)


def test_versions_serve_last_good_value_when_dockerhub_fails() -> None:
    with patch(
        "onyx.server.manage.get_state.requests.get", side_effect=_dockerhub_page
    ):
        good = get_versions()

    get_state._VERSIONS_CACHE.clear()  # simulate TTL expiry
    with patch(
        "onyx.server.manage.get_state.requests.get",
        side_effect=requests.ConnectionError("dockerhub down"),
    ):
        stale = get_versions()

    assert stale == good


def test_stale_value_is_served_without_refetch_during_cooldown() -> None:
    with patch(
        "onyx.server.manage.get_state.requests.get", side_effect=_dockerhub_page
    ):
        good = get_versions()

    get_state._VERSIONS_CACHE.clear()  # simulate TTL expiry
    with patch(
        "onyx.server.manage.get_state.requests.get",
        side_effect=requests.ConnectionError("dockerhub down"),
    ) as mock_get:
        assert get_versions() == good
        failed_calls = mock_get.call_count

        assert get_versions() == good
        assert mock_get.call_count == failed_calls


def test_versions_raise_when_dockerhub_fails_with_no_last_good_value() -> None:
    with (
        patch(
            "onyx.server.manage.get_state.requests.get",
            side_effect=requests.ConnectionError("dockerhub down"),
        ),
        pytest.raises(requests.ConnectionError),
    ):
        get_versions()


def test_failure_with_no_last_good_value_is_cached_for_the_cooldown() -> None:
    failed_at = 1000.0
    with (
        patch(
            "onyx.server.manage.get_state.requests.get",
            side_effect=requests.ConnectionError("dockerhub down"),
        ) as mock_get,
        patch.object(get_state.time, "monotonic", return_value=failed_at),
    ):
        with pytest.raises(requests.ConnectionError):
            get_versions()
        failed_calls = mock_get.call_count

        with pytest.raises(OnyxError) as first:
            get_versions()
        with pytest.raises(OnyxError) as second:
            get_versions()
        assert mock_get.call_count == failed_calls

    # Fresh errors each time, so tracebacks do not pile up across requests.
    assert first.value is not second.value
    assert first.value.error_code == OnyxErrorCode.SERVICE_UNAVAILABLE
    assert len(traceback.extract_tb(second.value.__traceback__)) == len(
        traceback.extract_tb(first.value.__traceback__)
    )

    after_cooldown = failed_at + get_state._VERSIONS_FAILURE_COOLDOWN_SECONDS
    with (
        patch(
            "onyx.server.manage.get_state.requests.get", side_effect=_dockerhub_page
        ) as mock_get,
        patch.object(get_state.time, "monotonic", return_value=after_cooldown),
    ):
        versions = get_versions()

    assert mock_get.call_count == len(get_state._DOCKERHUB_REPOS)
    assert versions.stable.onyx == "v3.2.0"
    assert get_state._LAST_VERSIONS_FAILURE_AT is None


def test_concurrent_misses_share_one_failed_fetch() -> None:
    callers = 8
    start = threading.Barrier(callers)

    def _call() -> Exception | None:
        start.wait()
        try:
            get_versions()
        except Exception as e:
            return e
        return None

    with (
        patch.object(
            get_state,
            "_fetch_versions",
            side_effect=requests.ConnectionError("dockerhub down"),
        ) as mock_fetch,
        ThreadPoolExecutor(max_workers=callers) as executor,
    ):
        errors = list(executor.map(lambda _: _call(), range(callers)))

    assert all(error is not None for error in errors)
    # Callers queued behind the failed fetch hit the cooldown.
    assert mock_fetch.call_count == 1


def test_dockerhub_requests_are_bounded() -> None:
    def _endless_page(url: str, timeout: int) -> MagicMock:  # noqa: ARG001
        response = _dockerhub_page(url, timeout)
        page = response.json.return_value
        page["next"] = "https://hub.docker.com/v2/next-page"
        return response

    with patch(
        "onyx.server.manage.get_state.requests.get", side_effect=_endless_page
    ) as mock_get:
        get_versions()

    repo_count = len(get_state._DOCKERHUB_REPOS)
    assert mock_get.call_count == repo_count * get_state._DOCKERHUB_MAX_PAGES
    assert get_state._DOCKERHUB_MAX_PAGES == 2
    first_page_urls = [
        call.args[0]
        for call in mock_get.call_args_list
        if "next-page" not in call.args[0]
    ]
    assert len(first_page_urls) == repo_count
    assert all("page_size=100" in url for url in first_page_urls)
    assert all(call.kwargs["timeout"] == 5 for call in mock_get.call_args_list)


def test_concurrent_misses_share_one_fetch() -> None:
    callers = 8
    start = threading.Barrier(callers)

    def _call() -> Any:
        start.wait()
        return get_versions()

    with (
        patch(
            "onyx.server.manage.get_state.requests.get", side_effect=_dockerhub_page
        ) as mock_get,
        ThreadPoolExecutor(max_workers=callers) as executor,
    ):
        results = list(executor.map(lambda _: _call(), range(callers)))

    assert all(result == results[0] for result in results)
    assert mock_get.call_count == len(get_state._DOCKERHUB_REPOS)
