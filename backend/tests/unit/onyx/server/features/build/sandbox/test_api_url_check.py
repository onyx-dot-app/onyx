from unittest.mock import MagicMock, patch

import httpx
import pytest

from onyx.server.features.build.sandbox.util import api_url_check


@pytest.fixture(autouse=True)
def _reset_validation_cache() -> None:
    api_url_check._validated = False


def _response(status: int, json_body: object = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    if json_body is None:
        resp.json.side_effect = ValueError("not json")
    else:
        resp.json.return_value = json_body
    return resp


def _health_response() -> MagicMock:
    return _response(200, {"success": True, "message": "ok"})


def test_missing_api_prefix_raises_with_corrected_url() -> None:
    def fake_get(url: str, **_: object) -> MagicMock:
        if url == "https://onyx.example/health":
            return _response(404)
        assert url == "https://onyx.example/api/health"
        return _health_response()

    with patch.object(api_url_check.httpx, "get", side_effect=fake_get):
        with pytest.raises(RuntimeError) as exc_info:
            api_url_check.validate_sandbox_api_url("https://onyx.example")

    assert "'https://onyx.example/api'" in str(exc_info.value)


def test_redirected_web_page_does_not_mask_missing_prefix() -> None:
    # An ingress that redirects the unprefixed /health to a login page still
    # answers 200 — the body, not the status, proves it isn't the API.
    def fake_get(url: str, **_: object) -> MagicMock:
        if url == "https://onyx.example/health":
            return _response(200, json_body=None)  # HTML login page
        assert url == "https://onyx.example/api/health"
        return _health_response()

    with patch.object(api_url_check.httpx, "get", side_effect=fake_get):
        with pytest.raises(RuntimeError) as exc_info:
            api_url_check.validate_sandbox_api_url("https://onyx.example")

    assert "'https://onyx.example/api'" in str(exc_info.value)


def test_reachable_url_passes_and_caches() -> None:
    with patch.object(
        api_url_check.httpx, "get", return_value=_health_response()
    ) as probe:
        api_url_check.validate_sandbox_api_url("http://api:8080")
        api_url_check.validate_sandbox_api_url("http://api:8080")

    probe.assert_called_once()


def test_auth_guarded_health_counts_as_reachable() -> None:
    with patch.object(api_url_check.httpx, "get", return_value=_response(403)):
        api_url_check.validate_sandbox_api_url("https://onyx.example/api")


def test_unreachable_probe_never_blocks() -> None:
    with patch.object(
        api_url_check.httpx,
        "get",
        side_effect=httpx.ConnectError("egress blocked"),
    ):
        api_url_check.validate_sandbox_api_url("https://onyx.example/api")


def test_double_404_warns_without_raising() -> None:
    with patch.object(api_url_check.httpx, "get", return_value=_response(404)):
        api_url_check.validate_sandbox_api_url("https://onyx.example")


def test_spa_catch_all_on_both_paths_warns_without_raising() -> None:
    # A frontend catch-all answering 200 HTML for every path gives no
    # evidence either way — never block.
    with patch.object(
        api_url_check.httpx, "get", return_value=_response(200, json_body=None)
    ):
        api_url_check.validate_sandbox_api_url("https://onyx.example")
