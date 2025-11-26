# from __future__ import annotations

# from collections.abc import Sequence

# import requests

# from onyx.agents.agent_search.dr.sub_agents.web_search.models import (
#     WebContent,
# )
# from onyx.agents.agent_search.dr.sub_agents.web_search.models import (
#     WebContentProvider,
# )
# from onyx.file_processing.html_utils import ParsedHTML
# from onyx.file_processing.html_utils import web_html_cleanup
# from onyx.utils.logger import setup_logger

# logger = setup_logger()

# DEFAULT_TIMEOUT_SECONDS = 15
# DEFAULT_USER_AGENT = "OnyxWebCrawler/1.0 (+https://www.onyx.app)"


# class OnyxWebCrawler(WebContentProvider):
#     """
#     Lightweight built-in crawler that fetches HTML directly and extracts readable text.
#     Acts as the default content provider when no external crawler (e.g. Firecrawl) is
#     configured.
#     """

#     def __init__(
#         self,
#         *,
#         timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
#         user_agent: str = DEFAULT_USER_AGENT,
#     ) -> None:
#         self._timeout_seconds = timeout_seconds
#         self._headers = {
#             "User-Agent": user_agent,
#             "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
#         }

#     def contents(self, urls: Sequence[str]) -> list[WebContent]:
#         results: list[WebContent] = []
#         for url in urls:
#             results.append(self._fetch_url(url))
#         return results

#     def _fetch_url(self, url: str) -> WebContent:
#         try:
#             response = requests.get(
#                 url, headers=self._headers, timeout=self._timeout_seconds
#             )
#         except Exception as exc:  # pragma: no cover - network failures vary
#             logger.warning(
#                 "Onyx crawler failed to fetch %s (%s)",
#                 url,
#                 exc.__class__.__name__,
#             )
#             return WebContent(
#                 title="",
#                 link=url,
#                 full_content="",
#                 published_date=None,
#                 scrape_successful=False,
#             )

#         if response.status_code >= 400:
#             logger.warning("Onyx crawler received %s for %s", response.status_code, url)
#             return WebContent(
#                 title="",
#                 link=url,
#                 full_content="",
#                 published_date=None,
#                 scrape_successful=False,
#             )

#         try:
#             parsed: ParsedHTML = web_html_cleanup(response.text)
#             text_content = parsed.cleaned_text or ""
#             title = parsed.title or ""
#         except Exception as exc:
#             logger.warning(
#                 "Onyx crawler failed to parse %s (%s)", url, exc.__class__.__name__
#             )
#             text_content = ""
#             title = ""

#         return WebContent(
#             title=title,
#             link=url,
#             full_content=text_content,
#             published_date=None,
#             scrape_successful=bool(text_content.strip()),
#         )
