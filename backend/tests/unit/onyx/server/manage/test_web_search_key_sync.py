from __future__ import annotations

from onyx.server.manage.web_search.api import (
    _synced_content_config,
    _synced_search_config,
)
from onyx.tools.tool_implementations.web_search.models import WebContentProviderConfig
from shared_configs.enums import WebContentProviderType, WebSearchProviderType


def test_search_to_content_sync_seeds_cloud_scrape_url_by_default() -> None:
    config = _synced_content_config(WebContentProviderType.FIRECRAWL, None)

    assert config == WebContentProviderConfig(
        base_url="https://api.firecrawl.dev/v2/scrape"
    )


def test_search_to_content_sync_follows_self_hosted_origin() -> None:
    config = _synced_content_config(
        WebContentProviderType.FIRECRAWL,
        {"base_url": "http://firecrawl.internal:3002/v2/search"},
    )

    assert config == WebContentProviderConfig(
        base_url="http://firecrawl.internal:3002/v2/scrape"
    )


def test_search_to_content_sync_skips_unrecognized_url() -> None:
    config = _synced_content_config(
        WebContentProviderType.FIRECRAWL,
        {"base_url": "https://proxy.example.com/firecrawl"},
    )

    assert config is None


def test_search_to_content_sync_ignores_other_providers() -> None:
    assert _synced_content_config(WebContentProviderType.TAVILY, None) is None
    assert _synced_content_config(WebContentProviderType.EXA, None) is None


def test_content_to_search_sync_seeds_cloud_search_url_by_default() -> None:
    config = _synced_search_config(WebSearchProviderType.FIRECRAWL, None)

    assert config == {"base_url": "https://api.firecrawl.dev/v2/search"}


def test_content_to_search_sync_follows_self_hosted_origin() -> None:
    config = _synced_search_config(
        WebSearchProviderType.FIRECRAWL,
        WebContentProviderConfig(base_url="http://firecrawl.internal:3002/v2/scrape"),
    )

    assert config == {"base_url": "http://firecrawl.internal:3002/v2/search"}


def test_content_to_search_sync_skips_unrecognized_url() -> None:
    config = _synced_search_config(
        WebSearchProviderType.FIRECRAWL,
        WebContentProviderConfig(base_url="https://proxy.example.com/firecrawl"),
    )

    assert config is None


def test_content_to_search_sync_ignores_other_providers() -> None:
    assert _synced_search_config(WebSearchProviderType.TAVILY, None) is None
    assert _synced_search_config(WebSearchProviderType.EXA, None) is None
