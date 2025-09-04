from datetime import datetime
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from onyx.agents.agent_search.dr.sub_agents.internet_search.models import (
    InternetSearchProvider,
    InternetSearchResult,
    InternetContent,
)
from onyx.configs.chat_configs import GOOGLE_API_KEY, GOOGLE_CSE_ID
from onyx.utils.retry_wrapper import retry_builder
from onyx.utils.logger import setup_logger

import requests
from bs4 import BeautifulSoup

logger = setup_logger()

class GoogleClient(InternetSearchProvider):
    def __init__(
        self, api_key: str | None = GOOGLE_API_KEY, cse_id: str | None = GOOGLE_CSE_ID
    ) -> None:
        if not api_key or not cse_id:
            raise ValueError(
                "Google API key and CSE ID must be set in environment variables."
            )
        try:
            self.service = build("customsearch", "v1", developerKey=api_key)
            self.cse_id = cse_id
        except HttpError as e:
            logger.error(f"Failed to build Google Custom Search service: {e}")
            raise ValueError("Failed to initialize Google search client.")

    @retry_builder(tries=3, delay=1, backoff=2)
    def search(self, query: str) -> list[InternetSearchResult]:
        try:
            response = (
                self.service.cse()
                .list(q=query, cx=self.cse_id, num=10)
                .execute()
            )
            results = response.get("items", [])
            return [
                InternetSearchResult(
                    title=result.get("title", ""),
                    link=result.get("link", ""),
                    snippet=result.get("snippet", ""),
                )
                for result in results
            ]
        except HttpError as e:
            logger.error(f"Google Search API call failed: {e}")
            return []

    def contents(self, urls: list[str]) -> list[InternetContent]:
        contents_list: list[InternetContent] = []
        for url in urls:
            try:
                response = requests.get(url, timeout=5)
                response.raise_for_status()

                soup = BeautifulSoup(response.text, 'html.parser')
                title = soup.title.string if soup.title else ""
                
                full_content = ' '.join(soup.stripped_strings)

                contents_list.append(
                    InternetContent(
                        title=title,
                        link=url,
                        full_content=full_content,
                    )
                )
            except requests.exceptions.RequestException as e:
                logger.error(f"Failed to fetch content from {url}: {e}")
            except Exception as e:
                logger.error(f"Error parsing content from {url}: {e}")
        
        return contents_list