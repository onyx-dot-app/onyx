import requests
from fastapi import HTTPException

from onyx.tools.tool_implementations.web_search.models import (
    WebSearchProvider,
)
from onyx.tools.tool_implementations.web_search.models import (
    WebSearchResult,
)
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import retry_builder

logger = setup_logger()


class SearXNGClient(WebSearchProvider):
    def __init__(
        self,
        searxng_base_url: str,
        num_results: int = 10,
    ) -> None:
        logger.debug(f"Initializing SearXNGClient with base URL: {searxng_base_url}")
        self._searxng_base_url = searxng_base_url
        self._num_results = num_results

    @retry_builder(tries=3, delay=1, backoff=2)
    def search(self, query: str) -> list[WebSearchResult]:
        payload = {
            "q": query,
            "format": "json",
        }
        logger.debug(
            f"Searching with payload: {payload} to {self._searxng_base_url}/search"
        )
        response = requests.post(
            f"{self._searxng_base_url}/search",
            data=payload,
        )
        response.raise_for_status()

        results = response.json()
        result_list = results.get("results", [])
        # SearXNG doesn't support limiting results via API parameters,
        # so we limit client-side after receiving the response
        limited_results = result_list[: self._num_results]
        return [
            WebSearchResult(
                title=result["title"],
                link=result["url"],
                snippet=result["content"],
            )
            for result in limited_results
        ]

    def test_connection(self) -> dict[str, str]:
        try:
            logger.debug(f"Testing connection to {self._searxng_base_url}/config")
            response = requests.get(f"{self._searxng_base_url}/config")
            logger.debug(f"Response: {response.status_code}, text: {response.text}")
            response.raise_for_status()
        except requests.HTTPError as e:
            status_code = e.response.status_code
            logger.debug(
                f"HTTPError: status_code={status_code}, e.response={e.response.status_code if e.response else None}, error={e}"
            )
            if status_code == 429:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "This SearXNG instance does not allow API requests. "
                        "Use a private instance and configure it to allow bots."
                    ),
                ) from e
            elif status_code == 404:
                raise HTTPException(
                    status_code=400,
                    detail="This SearXNG instance was not found. Please check the URL and try again.",
                ) from e
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"SearXNG connection failed (status {status_code}): {str(e)}",
                ) from e

        # Not a sure way to check if this is a SearXNG instance as opposed to some other website that
        # happens to have a /config endpoint containing a "brand" key with a "GIT_URL" key with value
        # "https://github.com/searxng/searxng". I don't think that would happen by coincidence, so I
        # think this is a good enough check for now. I'm open for suggestions on improvements.
        config = response.json()
        if (
            config.get("brand", {}).get("GIT_URL")
            != "https://github.com/searxng/searxng"
        ):
            raise HTTPException(
                status_code=400,
                detail="This does not appear to be a SearXNG instance. Please check the URL and try again.",
            )

        # Test that JSON mode is enabled by performing a simple search
        self._test_json_mode()

        logger.info("Web search provider test succeeded for SearXNG.")
        return {"status": "ok"}

    def _test_json_mode(self) -> None:
        """Test that JSON format is enabled in SearXNG settings.

        SearXNG requires JSON format to be explicitly enabled in settings.yml.
        If it's not enabled, the search endpoint returns a 403.
        """
        try:
            payload = {
                "q": "test",
                "format": "json",
            }
            response = requests.post(
                f"{self._searxng_base_url}/search",
                data=payload,
                timeout=5,
            )
            response.raise_for_status()
        except requests.HTTPError as e:
            status_code = e.response.status_code if e.response is not None else None
            if status_code == 403:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Got a 403 response when trying to reach SearXNG. This likely means that "
                        "JSON format is not enabled on this SearXNG instance. "
                        "Please enable JSON format in your SearXNG settings.yml file by adding "
                        "'json' to the 'search.formats' list."
                    ),
                ) from e
            raise HTTPException(
                status_code=400,
                detail=f"Failed to test search on SearXNG instance (status {status_code}): {str(e)}",
            ) from e
