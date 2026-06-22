import json
from urllib.parse import urlsplit


import requests
from fastapi import HTTPException

from onyx.tools.tool_implementations.web_search.models import WebSearchProvider
from onyx.tools.tool_implementations.web_search.models import WebSearchResult
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import retry_builder

logger = setup_logger()

KEENABLE_DEFAULT_BASE_URL = "https://api.keenable.ai"
KEENABLE_REQUEST_TIMEOUT_SECONDS = 30


class KeenableClient(WebSearchProvider):
    """Keenable web search provider.

    Keenable is a web search API built for AI agents. Unlike most providers it
    works without an API key by default: with no key the keyless public endpoint
    is used. Passing an API key uses the authenticated endpoint and lifts rate
    limits.
    """

    def __init__(
        self,
        api_key: str | None = None,
        num_results: int = 10,
        base_url: str | None = None,
    ) -> None:
        self._api_key = (api_key or "").strip() or None
        self._num_results = num_results
        self._base_url = self._normalize_base_url(base_url)

    @staticmethod
    def _normalize_base_url(base_url: str | None) -> str:
        base = (base_url or KEENABLE_DEFAULT_BASE_URL).rstrip("/")
        parsed = urlsplit(base)
        if parsed.hostname:
            if parsed.scheme == "https":
                return base
            # Permit plain http only against a loopback host (local dev).
            if parsed.scheme == "http" and parsed.hostname in {
                "localhost",
                "127.0.0.1",
                "::1",
            }:
                return base
        raise ValueError(
            f"Keenable base URL must be an https:// URL with a host, got {base!r}"
        )

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "keenable-onyx",
            # Attribution header the Keenable backend segments traffic by.
            "X-Keenable-Title": "Onyx",
        }
        if self._api_key:
            headers["X-API-Key"] = self._api_key
        return headers

    @retry_builder(tries=3, delay=1, backoff=2)
    def search(self, query: str) -> list[WebSearchResult]:
        # Keyless public endpoint by default; keyed endpoint when a key is set.
        path = "/v1/search" if self._api_key else "/v1/search/public"
        response = requests.post(
            f"{self._base_url}{path}",
            headers=self._headers(),
            data=json.dumps({"query": query, "mode": "pro"}),
            timeout=KEENABLE_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()

        body = response.json()
        results = body.get("results") if isinstance(body, dict) else None
        if not isinstance(results, list):
            return []

        validated_results: list[WebSearchResult] = []
        for result in results[: self._num_results]:
            if not isinstance(result, dict):
                continue
            link = (result.get("url") or "").strip()
            if not link:
                continue
            validated_results.append(
                WebSearchResult(
                    title=(result.get("title") or "").strip(),
                    link=link,
                    snippet=(result.get("description") or "").strip(),
                    author=result.get("author"),
                    published_date=None,
                )
            )

        return validated_results

    def test_connection(self) -> dict[str, str]:
        try:
            test_results = self.search("test")
            if not test_results or not any(result.link for result in test_results):
                raise HTTPException(
                    status_code=400,
                    detail="Keenable validation failed: search returned no results.",
                )
        except HTTPException:
            raise
        except Exception as e:
            error_msg = str(e)
            if any(t in error_msg.lower() for t in ("api", "key", "auth")):
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid Keenable API key: {error_msg}",
                ) from e
            raise HTTPException(
                status_code=400,
                detail=f"Keenable validation failed: {error_msg}",
            ) from e

        logger.info("Web search provider test succeeded for Keenable.")
        return {"status": "ok"}
