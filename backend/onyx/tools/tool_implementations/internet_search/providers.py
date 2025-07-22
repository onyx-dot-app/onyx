from typing import Any

import requests
from pydantic import BaseModel

from onyx.configs.chat_configs import BING_API_KEY
from onyx.configs.chat_configs import EXA_API_KEY
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.tools.tool_implementations.internet_search.models import InternetSearchResult
from onyx.tools.tool_implementations.internet_search.models import ProviderConfig
from onyx.tools.tool_implementations.internet_search.models import ProviderType
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import retry_builder

logger = setup_logger()


PROVIDER_CONFIGS = {
    ProviderType.BING.value: ProviderConfig(
        api_key=BING_API_KEY or "",
        api_base="https://api.bing.microsoft.com/v7.0/search",
        headers={
            "Ocp-Apim-Subscription-Key": BING_API_KEY or "",
            "Content-Type": "application/json",
        },
        query_param_name="q",
        num_results_param="count",
        search_params={},
        request_method="GET",
        results_path=["webPages", "value"],
        result_mapping={
            "title": "name",
            "link": "url",
            "full_content": "snippet",
            "published_date": "datePublished",
        },
    ),
    ProviderType.EXA.value: ProviderConfig(
        api_key=EXA_API_KEY or "",
        api_base="https://api.exa.ai/search",
        headers={
            "x-api-key": EXA_API_KEY or "",
            "Content-Type": "application/json",
        },
        query_param_name="query",
        num_results_param="num_results",
        search_params={
            "type": "auto",
            "contents": {
                "text": True,
                "livecrawl": "preferred",
            },
        },
        request_method="POST",
        results_path=["results"],
        result_mapping={
            "title": "title",
            "link": "url",
            "published_date": "publishedDate",
            "full_content": "text",
            "author": "author",
        },
    ),
}


class InternetSearchProvider(BaseModel):
    name: str
    config: ProviderConfig
    num_results: int = 10

    @retry_builder(tries=3, delay=1, backoff=2)
    def _search_get(self, query: str, token_budget: int) -> requests.Response:
        params = {
            self.config.query_param_name: query,
            **self.config.search_params,
        }

        # Set num_results using the configured parameter name
        if self.config.num_results_param:
            params[self.config.num_results_param] = self.num_results

        response = requests.get(
            self.config.api_base,
            headers=self.config.headers,
            params=params,
            timeout=30,
        )
        response.raise_for_status()
        return response

    @retry_builder(tries=3, delay=1, backoff=2)
    def _search_post(self, query: str, token_budget: int) -> requests.Response:
        payload = {
            self.config.query_param_name: query,
            **self.config.search_params,
        }

        # Set num_results using the configured parameter name
        if self.config.num_results_param:
            payload[self.config.num_results_param] = self.num_results

        response = requests.post(
            self.config.api_base,
            headers=self.config.headers,
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        return response

    def _extract_global_field(self, data: dict[str, Any], field_path: list[str]) -> Any:
        """Extract a global field from the API response using a path"""
        current = data
        for key in field_path:
            if not isinstance(current, dict) or key not in current:
                return None
            current = current[key]
        return current

    def _navigate_to_results(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Navigate to results list using the configured path"""
        current = data
        for key in self.config.results_path:
            if not isinstance(current, dict) or key not in current:
                return []
            current = current[key]

        return current if isinstance(current, list) else []

    def _extract_results(self, data: dict[str, Any]) -> list[InternetSearchResult]:
        """Extract results from API response based on provider configuration"""
        results = []

        # Extract global fields that apply to all results (e.g. rag_context)
        global_values: dict[str, Any] = {}
        if hasattr(self.config, "global_fields") and self.config.global_fields:
            for field_name, field_path in self.config.global_fields.items():
                global_values[field_name] = self._extract_global_field(data, field_path)

        # Navigate to final results list using the configured path
        results_list = self._navigate_to_results(data)
        if not results_list:
            return []

        for web_source in results_list:
            # Skip invalid entries
            if not web_source or not hasattr(web_source, "get"):
                logger.warning(f"Skipping invalid result entry: {type(web_source)}")
                continue

            # Extract field values using the mapping
            title_key = self.config.result_mapping.get("title", "")
            title = web_source.get(title_key, "") if title_key else ""

            link_key = self.config.result_mapping.get("link", "")
            link = web_source.get(link_key, "") if link_key else ""

            full_content_key = self.config.result_mapping.get("full_content", "")
            full_content = (
                web_source.get(full_content_key, "") if full_content_key else ""
            )

            # Skip result if any required fields are missing (published_date is optional)
            if not title or not link or not full_content:
                logger.warning("Skipping result with missing required fields")
                continue

            published_date_key = self.config.result_mapping.get("published_date", "")
            published_date_str = (
                web_source.get(published_date_key, "") if published_date_key else ""
            )

            # Parse published_date string to datetime object
            published_date = None
            if published_date_str:
                try:
                    published_date = time_str_to_utc(published_date_str)
                except ValueError:
                    logger.warning(
                        f"Failed to parse published_date: {published_date_str}"
                    )

            internet_search_result = InternetSearchResult(
                title=title,
                link=link,
                published_date=published_date,
                full_content=full_content,
                rag_context=global_values.get("rag_context", ""),
            )
            results.append(internet_search_result)

        return results

    def search(self, query: str, token_budget: int) -> list[InternetSearchResult]:
        """Perform search using the configured provider"""
        try:
            if self.config.request_method.upper() == "GET":
                response = self._search_get(query, token_budget)
            else:
                response = self._search_post(query, token_budget)

            data = response.json()

            results = self._extract_results(data)

            return results

        except Exception as e:
            logger.error(f"{self.name} search failed: {e}")
            return []


def get_available_providers() -> dict[str, InternetSearchProvider]:
    """Get all available internet search providers"""
    providers = {}

    for provider_name, config in PROVIDER_CONFIGS.items():
        try:
            if config.api_key:
                providers[provider_name] = InternetSearchProvider(
                    name=provider_name, config=config
                )
        except Exception as e:
            logger.warning(f"{provider_name} provider not available: {e}")

    if not providers:
        logger.warning("No internet search providers found")

    return providers


def get_default_provider() -> InternetSearchProvider | None:
    """Get the default internet search provider"""
    providers = get_available_providers()

    for provider_type in [ProviderType.BING, ProviderType.EXA]:
        if provider_type.value in providers:
            return providers[provider_type.value]

    logger.warning("No internet search providers found")
    return None


def get_provider_by_name(name: str) -> InternetSearchProvider | None:
    """Get a specific provider by name"""
    providers = get_available_providers()

    if not providers or name not in providers:
        logger.warning(f"Internet search provider '{name}' not found")
        return None

    return providers[name]
