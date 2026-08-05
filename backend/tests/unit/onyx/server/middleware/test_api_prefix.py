import pytest

from onyx.server.middleware import api_prefix


@pytest.mark.parametrize(
    ("configured_prefix", "path", "expected"),
    [
        ("v2", "/v2/gateway/v1/models", "/gateway/v1/models"),
        ("/v2/", "/v2/gateway", "/gateway"),
        ("v2", "/v2", "/"),
        ("", "/gateway", "/gateway"),
        ("", "/api/gateway", "/gateway"),
        ("", "/apigateway", "/apigateway"),
        ("v2", "/v2gateway", "/v2gateway"),
        ("v2", "/api/gateway", "/api/gateway"),
    ],
)
def test_strip_api_prefix(
    monkeypatch: pytest.MonkeyPatch,
    configured_prefix: str,
    path: str,
    expected: str,
) -> None:
    monkeypatch.setattr(api_prefix, "APP_API_PREFIX", configured_prefix)
    assert api_prefix.strip_api_prefix(path) == expected
