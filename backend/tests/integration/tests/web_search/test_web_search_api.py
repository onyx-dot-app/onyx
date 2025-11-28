import os

import pytest
import requests

from shared_configs.enums import WebContentProviderType
from shared_configs.enums import WebSearchProviderType
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.test_models import DATestUser

pytestmark = pytest.mark.skipif(
    not os.environ.get("EXA_API_KEY"),
    reason="EXA_API_KEY not set; live web search tests require real credentials",
)


def _activate_exa_provider(admin_user: DATestUser) -> int:
    response = requests.post(
        f"{API_SERVER_URL}/admin/web-search/search-providers",
        json={
            "id": None,
            "name": "integration-exa-provider",
            "provider_type": WebSearchProviderType.EXA.value,
            "config": {},
            "api_key": os.environ["EXA_API_KEY"],
            "api_key_changed": True,
            "activate": True,
        },
        headers=admin_user.headers,
    )
    assert response.status_code == 200, response.text

    provider = response.json()
    assert provider["provider_type"] == WebSearchProviderType.EXA.value
    assert provider["is_active"] is True
    assert provider["has_api_key"] is True

    return provider["id"]


def test_web_search_endpoints_with_exa(
    reset: None,
    admin_user: DATestUser,
) -> None:
    provider_id = _activate_exa_provider(admin_user)
    assert isinstance(provider_id, int)

    search_request = {"queries": ["latest ai research news"], "max_results": 3}

    lite_response = requests.post(
        f"{API_SERVER_URL}/web-search/search-lite",
        json=search_request,
        headers=admin_user.headers,
    )
    assert lite_response.status_code == 200, lite_response.text
    lite_data = lite_response.json()

    assert lite_data["provider_type"] == WebSearchProviderType.EXA.value
    assert lite_data["results"], "Expected web search results from Exa"

    urls = [result["url"] for result in lite_data["results"] if result.get("url")][:2]
    assert urls, "Web search should return at least one URL"

    open_response = requests.post(
        f"{API_SERVER_URL}/web-search/open-urls",
        json={"urls": urls},
        headers=admin_user.headers,
    )
    assert open_response.status_code == 200, open_response.text
    open_data = open_response.json()

    assert open_data["provider_type"] == WebContentProviderType.ONYX_WEB_CRAWLER.value
    assert len(open_data["results"]) == len(urls)
    assert all("content" in result for result in open_data["results"])

    combined_response = requests.post(
        f"{API_SERVER_URL}/web-search/search",
        json=search_request,
        headers=admin_user.headers,
    )
    assert combined_response.status_code == 200, combined_response.text
    combined_data = combined_response.json()

    assert combined_data["search_provider_type"] == WebSearchProviderType.EXA.value
    assert (
        combined_data["content_provider_type"]
        == WebContentProviderType.ONYX_WEB_CRAWLER.value
    )
    assert combined_data["search_results"]

    unique_urls = list(
        dict.fromkeys(
            result["url"]
            for result in combined_data["search_results"]
            if result.get("url")
        )
    )
    assert len(combined_data["full_content_results"]) == len(unique_urls)
