import asyncio
from datetime import datetime
from typing import cast, List, Optional

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import httpx
from bs4 import BeautifulSoup

from onyx.agents.agent_search.dr.sub_agents.internet_search.models import (
    InternetSearchProvider,
    InternetSearchResult,
    InternetContent,
)
from onyx.configs.chat_configs import GOOGLE_API_KEY, GOOGLE_CSE_ID
from onyx.utils.retry_wrapper import retry_builder
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Use a global async client for efficiency across requests
async_client = httpx.AsyncClient(timeout=5.0)

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
    def search(self, query: str) -> List[InternetSearchResult]:
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
        except Exception as e:
            logger.error(f"Google Search API call failed: {e}")
            return []

    # Correction: La méthode `contents` doit être asynchrone pour utiliser `httpx.AsyncClient`.
    async def contents(self, urls: List[str]) -> List[InternetContent]:
        """
        Récupère le contenu de plusieurs URLs de manière asynchrone.
        """
        tasks = [self._fetch_url_content(url) for url in urls]
        # asyncio.gather permet d'exécuter toutes les requêtes en parallèle
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        contents_list: List[InternetContent] = []
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Error during content fetch: {result}")
                continue
            if result:
                contents_list.append(result)

        return contents_list

    async def _fetch_url_content(self, url: str) -> Optional[InternetContent]:
        """
        Méthode helper asynchrone pour la récupération et l'analyse d'une seule URL.
        """
        try:
            response = await async_client.get(url, timeout=5)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')
            title = soup.title.string if soup.title else ""
            
            # Utiliser .get_text() pour une extraction de texte plus propre
            full_content = soup.get_text(separator=' ', strip=True)

            return InternetContent(
                title=title,
                link=url,
                full_content=full_content,
            )
        except httpx.RequestError as e:
            logger.error(f"Failed to fetch content from {url}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error parsing content from {url}: {e}")
            return None