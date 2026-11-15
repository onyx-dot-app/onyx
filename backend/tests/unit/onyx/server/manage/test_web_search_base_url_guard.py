from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from onyx.db import web_search as web_search_db
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.web_search import api
from onyx.server.manage.web_search.models import (
    WebContentProviderTestRequest,
    WebContentProviderUpsertRequest,
    WebSearchProviderTestRequest,
    WebSearchProviderUpsertRequest,
)
from onyx.tools.tool_implementations.web_search.models import WebContentProviderConfig
from shared_configs.enums import WebContentProviderType, WebSearchProviderType

_STORED_URL = "https://api.firecrawl.dev/v2/search"
_OTHER_URL = "https://attacker.example/v2/search"


def _stored_row(provider_type: str, config: object) -> MagicMock:
    row = MagicMock()
    row.provider_type = provider_type
    row.config = config
    row.api_key.get_value.return_value = "fc-stored"
    return row


@pytest.fixture(autouse=True)
def cloud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "MULTI_TENANT", True)


def _test_request(base_url: str) -> WebSearchProviderTestRequest:
    return WebSearchProviderTestRequest(
        provider_type=WebSearchProviderType.FIRECRAWL,
        use_stored_key=True,
        config={"base_url": base_url},
    )


def test_test_endpoint_rejects_stored_credential_with_new_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = _stored_row("firecrawl", {"base_url": _STORED_URL})
    monkeypatch.setattr(api, "fetch_web_search_provider_by_type", lambda *_: stored)
    build = MagicMock()
    monkeypatch.setattr(api, "build_search_provider_from_config", build)

    with pytest.raises(OnyxError) as exc_info:
        api.test_search_provider(_test_request(_OTHER_URL), MagicMock(), MagicMock())

    assert exc_info.value.status_code == 400
    build.assert_not_called()


def test_test_endpoint_allows_stored_credential_with_same_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = _stored_row("firecrawl", {"base_url": _STORED_URL})
    monkeypatch.setattr(api, "fetch_web_search_provider_by_type", lambda *_: stored)
    provider = MagicMock()
    provider.test_connection.return_value = {"status": "ok"}
    build = MagicMock(return_value=provider)
    monkeypatch.setattr(api, "build_search_provider_from_config", build)

    result = api.test_search_provider(
        _test_request(_STORED_URL), MagicMock(), MagicMock()
    )

    assert result == {"status": "ok"}
    assert build.call_args.kwargs["api_key"] == "fc-stored"


def test_search_upsert_rejects_type_switch_on_stored_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = _stored_row("tavily", {})
    monkeypatch.setattr(api, "fetch_web_search_provider_by_name", lambda *_: None)
    monkeypatch.setattr(api, "fetch_web_search_provider_by_id", lambda *_: stored)
    upsert = MagicMock()
    monkeypatch.setattr(api, "upsert_web_search_provider", upsert)

    request = WebSearchProviderUpsertRequest(
        id=1,
        name="Tavily",
        provider_type=WebSearchProviderType.FIRECRAWL,
        api_key_changed=False,
        config={},
    )
    with pytest.raises(OnyxError):
        api.upsert_search_provider_endpoint(request, MagicMock(), MagicMock())

    upsert.assert_not_called()


def test_content_upsert_rejects_new_base_url_on_stored_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = _stored_row(
        "firecrawl",
        WebContentProviderConfig(base_url="https://api.firecrawl.dev/v2/scrape"),
    )
    monkeypatch.setattr(api, "fetch_web_content_provider_by_name", lambda *_: None)
    monkeypatch.setattr(api, "fetch_web_content_provider_by_id", lambda *_: stored)
    upsert = MagicMock()
    monkeypatch.setattr(api, "upsert_web_content_provider", upsert)

    request = WebContentProviderUpsertRequest(
        id=1,
        name="Firecrawl",
        provider_type=WebContentProviderType.FIRECRAWL,
        api_key_changed=False,
        config=WebContentProviderConfig(base_url="https://attacker.example/v2/scrape"),
    )
    with pytest.raises(OnyxError):
        api.upsert_content_provider_endpoint(request, MagicMock(), MagicMock())

    upsert.assert_not_called()


def test_sibling_base_url_update_keeps_other_config() -> None:
    row = MagicMock()
    row.config = {"base_url": "https://old.example/v2/search", "tbs": "qdr:d"}
    db_session = MagicMock()
    db_session.scalars.return_value.first.return_value = row

    web_search_db.set_web_search_provider_base_url(
        name="Firecrawl", base_url=_STORED_URL, db_session=db_session
    )

    assert row.config == {"base_url": _STORED_URL, "tbs": "qdr:d"}


def test_content_test_endpoint_rejects_stored_credential_with_new_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = _stored_row(
        "firecrawl",
        WebContentProviderConfig(base_url="https://api.firecrawl.dev/v2/scrape"),
    )
    monkeypatch.setattr(api, "fetch_web_content_provider_by_type", lambda *_: stored)
    build = MagicMock()
    monkeypatch.setattr(api, "build_content_provider_from_config", build)

    request = WebContentProviderTestRequest(
        provider_type=WebContentProviderType.FIRECRAWL,
        use_stored_key=True,
        config=WebContentProviderConfig(base_url="https://attacker.example/v2/scrape"),
    )
    with pytest.raises(OnyxError):
        api.test_content_provider(request, MagicMock(), MagicMock())

    build.assert_not_called()
