import os

import pytest
import requests

from shared_configs.enums import WebContentProviderType
from shared_configs.enums import WebSearchProviderType
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.test_models import DATestUser


class TestOnyxWebCrawler:
    """
    Integration tests for the Onyx web crawler functionality.

    These tests verify that the built-in crawler can fetch and parse
    content from public websites correctly.
    """

    def test_fetches_public_url_successfully(self, admin_user: DATestUser) -> None:
        """Test that the crawler can fetch content from a public URL."""
        response = requests.post(
            f"{API_SERVER_URL}/web-search/open-urls",
            json={"urls": ["https://example.com/"]},
            headers=admin_user.headers,
        )
        assert response.status_code == 200, response.text
        data = response.json()

        assert data["provider_type"] == WebContentProviderType.ONYX_WEB_CRAWLER.value
        assert len(data["results"]) == 1

        result = data["results"][0]
        assert "content" in result
        content = result["content"]

        # example.com is a static page maintained by IANA with known content
        # Verify exact expected text from the page
        assert "Example Domain" in content
        assert "This domain is for use in" in content
        assert "documentation" in content or "illustrative" in content

    def test_fetches_multiple_urls(self, admin_user: DATestUser) -> None:
        """Test that the crawler can fetch multiple URLs in one request."""
        response = requests.post(
            f"{API_SERVER_URL}/web-search/open-urls",
            json={
                "urls": [
                    "https://example.com/",
                    "https://www.iana.org/domains/reserved",
                ]
            },
            headers=admin_user.headers,
        )
        assert response.status_code == 200, response.text
        data = response.json()

        assert data["provider_type"] == WebContentProviderType.ONYX_WEB_CRAWLER.value
        assert len(data["results"]) == 2

        for result in data["results"]:
            assert "content" in result

    def test_handles_nonexistent_domain(self, admin_user: DATestUser) -> None:
        """Test that the crawler handles non-existent domains gracefully."""
        response = requests.post(
            f"{API_SERVER_URL}/web-search/open-urls",
            json={"urls": ["https://this-domain-definitely-does-not-exist-12345.com/"]},
            headers=admin_user.headers,
        )
        assert response.status_code == 200, response.text
        data = response.json()

        assert data["provider_type"] == WebContentProviderType.ONYX_WEB_CRAWLER.value

        # The API filters out docs with no title/content, so unreachable domains return no results
        assert data["results"] == []

    def test_handles_404_page(self, admin_user: DATestUser) -> None:
        """Test that the crawler handles 404 responses gracefully."""
        response = requests.post(
            f"{API_SERVER_URL}/web-search/open-urls",
            json={"urls": ["https://example.com/this-page-does-not-exist-12345"]},
            headers=admin_user.headers,
        )
        assert response.status_code == 200, response.text
        data = response.json()

        assert data["provider_type"] == WebContentProviderType.ONYX_WEB_CRAWLER.value

        # Non-200 responses are treated as non-content and filtered out
        assert data["results"] == []

    def test_https_url_with_path(self, admin_user: DATestUser) -> None:
        """Test that the crawler handles HTTPS URLs with paths correctly."""
        response = requests.post(
            f"{API_SERVER_URL}/web-search/open-urls",
            json={"urls": ["https://www.iana.org/about"]},
            headers=admin_user.headers,
        )
        assert response.status_code == 200, response.text
        data = response.json()

        assert len(data["results"]) == 1
        result = data["results"][0]
        assert "content" in result


class TestSsrfProtection:
    """
    Integration tests for SSRF protection on the /open-urls endpoint.

    These tests verify that the endpoint correctly blocks requests to:
    - Internal/private IP addresses
    - Cloud metadata endpoints
    - Blocked hostnames (Kubernetes, cloud metadata, etc.)
    """

    def test_blocks_localhost_ip(self, admin_user: DATestUser) -> None:
        """Test that requests to localhost (127.0.0.1) are blocked."""
        response = requests.post(
            f"{API_SERVER_URL}/web-search/open-urls",
            json={"urls": ["http://127.0.0.1/"]},
            headers=admin_user.headers,
        )
        assert response.status_code == 200
        data = response.json()
        # URL should be processed but return empty content (blocked by SSRF protection)
        assert len(data["results"]) == 0 or data["results"][0]["content"] == ""

    def test_blocks_private_ip_10_network(self, admin_user: DATestUser) -> None:
        """Test that requests to 10.x.x.x private network are blocked."""
        response = requests.post(
            f"{API_SERVER_URL}/web-search/open-urls",
            json={"urls": ["http://10.0.0.1/"]},
            headers=admin_user.headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) == 0 or data["results"][0]["content"] == ""

    def test_blocks_private_ip_192_168_network(self, admin_user: DATestUser) -> None:
        """Test that requests to 192.168.x.x private network are blocked."""
        response = requests.post(
            f"{API_SERVER_URL}/web-search/open-urls",
            json={"urls": ["http://192.168.1.1/"]},
            headers=admin_user.headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) == 0 or data["results"][0]["content"] == ""

    def test_blocks_private_ip_172_network(self, admin_user: DATestUser) -> None:
        """Test that requests to 172.16-31.x.x private network are blocked."""
        response = requests.post(
            f"{API_SERVER_URL}/web-search/open-urls",
            json={"urls": ["http://172.16.0.1/"]},
            headers=admin_user.headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) == 0 or data["results"][0]["content"] == ""

    def test_blocks_aws_metadata_endpoint(self, admin_user: DATestUser) -> None:
        """Test that requests to AWS metadata endpoint (169.254.169.254) are blocked."""
        response = requests.post(
            f"{API_SERVER_URL}/web-search/open-urls",
            json={"urls": ["http://169.254.169.254/latest/meta-data/"]},
            headers=admin_user.headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) == 0 or data["results"][0]["content"] == ""

    def test_blocks_kubernetes_metadata_hostname(self, admin_user: DATestUser) -> None:
        """Test that requests to Kubernetes internal hostname are blocked."""
        response = requests.post(
            f"{API_SERVER_URL}/web-search/open-urls",
            json={"urls": ["http://kubernetes.default.svc.cluster.local/"]},
            headers=admin_user.headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) == 0 or data["results"][0]["content"] == ""

    def test_blocks_google_metadata_hostname(self, admin_user: DATestUser) -> None:
        """Test that requests to Google Cloud metadata hostname are blocked."""
        response = requests.post(
            f"{API_SERVER_URL}/web-search/open-urls",
            json={"urls": ["http://metadata.google.internal/"]},
            headers=admin_user.headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) == 0 or data["results"][0]["content"] == ""

    def test_blocks_localhost_with_port(self, admin_user: DATestUser) -> None:
        """Test that requests to localhost with custom port are blocked."""
        response = requests.post(
            f"{API_SERVER_URL}/web-search/open-urls",
            json={"urls": ["http://127.0.0.1:8080/metrics"]},
            headers=admin_user.headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) == 0 or data["results"][0]["content"] == ""

    def test_multiple_urls_filters_internal(self, admin_user: DATestUser) -> None:
        """Test that internal URLs are filtered while external URLs are processed."""
        response = requests.post(
            f"{API_SERVER_URL}/web-search/open-urls",
            json={
                "urls": [
                    "http://127.0.0.1/",  # Should be blocked
                    "http://192.168.1.1/",  # Should be blocked
                    "https://example.com/",  # Should be allowed (if reachable)
                ]
            },
            headers=admin_user.headers,
        )
        assert response.status_code == 200
        data = response.json()
        # Internal URLs should return empty content
        # The exact behavior depends on whether example.com is reachable
        # but internal URLs should definitely not return sensitive data
        for result in data["results"]:
            # Ensure no result contains internal network data
            content = result.get("content", "")
            # These patterns would indicate SSRF vulnerability
            assert "metrics" not in content.lower() or "example" in content.lower()
            assert "token" not in content.lower() or "example" in content.lower()


# Mark the Exa-dependent tests to skip if no API key
pytestmark_exa = pytest.mark.skipif(
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


@pytestmark_exa
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
