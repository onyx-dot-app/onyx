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

import httpx
from bs4 import BeautifulSoup

# La bibliothèque requests est remplacée par httpx pour le support asynchrone
# import requests 

logger = setup_logger()

# Définir un client HTTP asynchrone pour une utilisation plus efficace
# Il est recommandé de créer ce client une seule fois pour la durée de vie de l'application
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
        # Utilisation d'une gestion d'exceptions plus large pour éviter les plantages
        except Exception as e: 
            logger.error(f"Google Search API call failed: {e}")
            return []

    async def _fetch_url_content(self, url: str) -> InternetContent | None:
        """Méthode helper pour récupérer le contenu d'une URL de manière asynchrone."""
        try:
            response = await async_client.get(url)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')
            title = soup.title.string if soup.title else ""
            
            full_content = ' '.join(soup.stripped_strings)

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

    @retry_builder(tries=3, delay=1, backoff=2)
    async def contents(self, urls: list[str]) -> list[InternetContent]:
        """Récupère le contenu de plusieurs URLs de manière asynchrone."""
        tasks = [self._fetch_url_content(url) for url in urls]
        results = await asyncio.gather(*tasks)
        return [result for result in results if result is not None]