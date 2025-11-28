from onyx.agents.agent_search.dr.sub_agents.web_search.clients.onyx_web_crawler_client import (
    OnyxWebCrawlerClient,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.providers import (
    build_content_provider_from_config,
)
from shared_configs.enums import WebContentProviderType


def test_build_content_provider_returns_onyx_crawler() -> None:
    provider = build_content_provider_from_config(
        provider_type=WebContentProviderType.ONYX_WEB_CRAWLER,
        api_key=None,
        config={"timeout_seconds": "20"},
        provider_name="Built-in",
    )
    assert isinstance(provider, OnyxWebCrawlerClient)
