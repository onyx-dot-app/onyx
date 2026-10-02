from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from onyx.server.manage.web_search import api
from onyx.server.manage.web_search.models import WebSearchProviderTestRequest
from shared_configs.enums import WebSearchProviderType

_STORED_URL = "https://api.firecrawl.dev/v2/search"


@pytest.fixture
def stored_firecrawl(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    stored = MagicMock()
    stored.config = {"base_url": _STORED_URL}
    stored.api_key.get_value.return_value = "fc-stored"
    monkeypatch.setattr(api, "MULTI_TENANT", True)
    monkeypatch.setattr(api, "fetch_web_search_provider_by_type", lambda *_args: stored)
    return stored


def _request(base_url: str) -> WebSearchProviderTestRequest:
    return WebSearchProviderTestRequest(
        provider_type=WebSearchProviderType.FIRECRAWL,
        use_stored_key=True,
        config={"base_url": base_url},
    )


@pytest.mark.usefixtures("stored_firecrawl")
def test_stored_credential_rejected_when_base_url_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build = MagicMock()
    monkeypatch.setattr(api, "build_search_provider_from_config", build)

    with pytest.raises(HTTPException) as exc_info:
        api.test_search_provider(
            _request("https://attacker.example/v2/search"), MagicMock(), MagicMock()
        )

    assert exc_info.value.status_code == 400
    assert "Base URL cannot differ" in str(exc_info.value.detail)
    build.assert_not_called()


@pytest.mark.usefixtures("stored_firecrawl")
def test_stored_credential_allowed_when_base_url_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = MagicMock()
    provider.test_connection.return_value = {"status": "ok"}
    build = MagicMock(return_value=provider)
    monkeypatch.setattr(api, "build_search_provider_from_config", build)

    result = api.test_search_provider(_request(_STORED_URL), MagicMock(), MagicMock())

    assert result == {"status": "ok"}
    assert build.call_args.kwargs["api_key"] == "fc-stored"
