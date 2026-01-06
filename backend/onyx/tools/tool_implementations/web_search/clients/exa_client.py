import hashlib
import json
from collections.abc import Sequence

from exa_py import Exa
from exa_py.api import HighlightsContentsOptions
from fastapi import HTTPException

from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.redis.redis_pool import get_redis_client
from onyx.tools.tool_implementations.open_url.models import WebContent
from onyx.tools.tool_implementations.open_url.models import WebContentProvider
from onyx.tools.tool_implementations.web_search.models import (
    WebSearchProvider,
)
from onyx.tools.tool_implementations.web_search.models import (
    WebSearchResult,
)
from onyx.utils.logger import setup_logger
from onyx.utils.rate_limiting import get_exa_rate_limiter
from onyx.utils.retry_wrapper import retry_builder

logger = setup_logger()

# Global rate limiter shared across all ExaClient instances
# Exa has a 5 req/sec limit; we use 4 to leave headroom
_rate_limiter = get_exa_rate_limiter()

# Cache TTL for deduplicating parallel DR subagent queries
EXA_QUERY_CACHE_TTL = 1800  # 30 minutes


# TODO can probably break this up
class ExaClient(WebSearchProvider, WebContentProvider):
    def __init__(self, api_key: str, num_results: int = 10) -> None:
        self.exa = Exa(api_key=api_key)
        self._num_results = num_results

    def search(self, query: str) -> list[WebSearchResult]:
        """Cached search - cache hits bypass rate limiting."""
        # Build cache key
        cache_params = f"{query}:{self._num_results}"
        cache_hash = hashlib.sha256(cache_params.encode()).hexdigest()[:16]
        cache_key = f"exa_search_cache:{cache_hash}"

        # Try cache first (for deduplicating parallel DR subagent queries)
        redis_client = get_redis_client()
        try:
            cached = redis_client.get(cache_key)
            if cached:
                logger.info(f"Exa search cache HIT: {cache_key}")
                cached_str = (
                    cached.decode("utf-8") if isinstance(cached, bytes) else cached
                )
                data = json.loads(cached_str)
                return [WebSearchResult.model_validate(r) for r in data]
        except Exception as e:
            logger.warning(f"Exa search cache read error: {e}")

        # Cache miss - call rate-limited API
        results = self._search_api(query)

        # Cache the result
        try:
            redis_client.set(
                cache_key,
                json.dumps([r.model_dump(mode="json") for r in results]),
                ex=EXA_QUERY_CACHE_TTL,
            )
            logger.info(f"Exa search cache SET: {cache_key}")
        except Exception as e:
            logger.warning(f"Exa search cache write error: {e}")

        return results

    @retry_builder(tries=3, delay=1, backoff=2)
    @_rate_limiter
    def _search_api(self, query: str) -> list[WebSearchResult]:
        """Rate-limited API call to Exa search."""
        response = self.exa.search_and_contents(
            query,
            type="auto",
            highlights=HighlightsContentsOptions(
                num_sentences=2,
                highlights_per_url=1,
            ),
            num_results=self._num_results,
        )

        return [
            WebSearchResult(
                title=result.title or "",
                link=result.url,
                snippet=result.highlights[0] if result.highlights else "",
                author=result.author,
                published_date=(
                    time_str_to_utc(result.published_date)
                    if result.published_date
                    else None
                ),
            )
            for result in response.results
        ]

    def test_connection(self) -> dict[str, str]:
        try:
            test_results = self.search("test")
            if not test_results or not any(result.link for result in test_results):
                raise HTTPException(
                    status_code=400,
                    detail="API key validation failed: search returned no results.",
                )
        except HTTPException:
            raise
        except Exception as e:
            error_msg = str(e)
            if (
                "api" in error_msg.lower()
                or "key" in error_msg.lower()
                or "auth" in error_msg.lower()
            ):
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid Exa API key: {error_msg}",
                ) from e
            raise HTTPException(
                status_code=400,
                detail=f"Exa API key validation failed: {error_msg}",
            ) from e

        logger.info("Web search provider test succeeded for Exa.")
        return {"status": "ok"}

    def contents(self, urls: Sequence[str]) -> list[WebContent]:
        """Cached contents fetch - cache hits bypass rate limiting."""
        # Build cache key from sorted URLs (order doesn't matter for caching)
        urls_str = ",".join(sorted(urls))
        cache_hash = hashlib.sha256(urls_str.encode()).hexdigest()[:16]
        cache_key = f"exa_contents_cache:{cache_hash}"

        # Try cache first (for deduplicating parallel DR subagent queries)
        redis_client = get_redis_client()
        try:
            cached = redis_client.get(cache_key)
            if cached:
                logger.info(f"Exa contents cache HIT: {cache_key}")
                cached_str = (
                    cached.decode("utf-8") if isinstance(cached, bytes) else cached
                )
                data = json.loads(cached_str)
                return [WebContent.model_validate(r) for r in data]
        except Exception as e:
            logger.warning(f"Exa contents cache read error: {e}")

        # Cache miss - call rate-limited API
        results = self._contents_api(urls)

        # Cache the result
        try:
            redis_client.set(
                cache_key,
                json.dumps([r.model_dump(mode="json") for r in results]),
                ex=EXA_QUERY_CACHE_TTL,
            )
            logger.info(f"Exa contents cache SET: {cache_key}")
        except Exception as e:
            logger.warning(f"Exa contents cache write error: {e}")

        return results

    @retry_builder(tries=3, delay=1, backoff=2)
    @_rate_limiter
    def _contents_api(self, urls: Sequence[str]) -> list[WebContent]:
        """Rate-limited API call to Exa contents."""
        response = self.exa.get_contents(
            urls=list(urls),
            text=True,
            livecrawl="preferred",
        )

        return [
            WebContent(
                title=result.title or "",
                link=result.url,
                full_content=result.text or "",
                published_date=(
                    time_str_to_utc(result.published_date)
                    if result.published_date
                    else None
                ),
            )
            for result in response.results
        ]
