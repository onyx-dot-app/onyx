from datetime import datetime
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from onyx.agents.agent_search.dr.sub_agents.web_search.models import (
    InternetSearchProvider,
    InternetSearchResult,
    InternetContent,
)
from onyx.configs.chat_configs import GOOGLE_API_KEY, GOOGLE_CSE_ID
from onyx.utils.retry_wrapper import retry_builder
from onyx.utils.logger import setup_logger

import requests
from bs4 import BeautifulSoup
import os
import random
import time
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# --- Setup ---
logger = setup_logger()

# List of common User-Agents to rotate through
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/103.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.5 Safari/605.1.15',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:101.0) Gecko/20100101 Firefox/101.0',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/103.0.0.0 Safari/537.36',
]

class GoogleClient(InternetSearchProvider):
    def __init__(
            self, api_key: str | None = GOOGLE_API_KEY, cse_id: str | None = GOOGLE_CSE_ID
    ) -> None:
        # Check environment variables for keys if not passed
        api_key = api_key or os.environ.get("GOOGLE_API_KEY")
        cse_id = cse_id or os.environ.get("GOOGLE_CSE_ID")

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
        """
        Fetches the content of ALL provided URLs using Playwright for robust 
        JavaScript rendering. NOTE: This function no longer filters blocked domains.
        """
        contents_list: list[InternetContent] = []
        # All URLs are now considered for fetching
        urls_to_fetch = urls

        if not urls_to_fetch:
            return contents_list

        # 1. Initialize Playwright and start fetching
        try:
            with sync_playwright() as p:

                # Select a random User-Agent for this session
                random_user_agent = random.choice(USER_AGENTS)

                # Launch Chromium browser with randomized User-Agent and in headless mode
                browser = p.chromium.launch(
                    headless=True,
                    args=[f'--user-agent={random_user_agent}']
                )
                page = browser.new_page()

                for url in urls_to_fetch:
                    try:
                        # Implement a randomized delay between requests
                        sleep_time = random.uniform(2, 5)
                        logger.info(f"Pausing for {sleep_time:.2f}s before fetching {url}")
                        time.sleep(sleep_time)

                        # Navigate to the URL and wait for network activity to settle
                        page.goto(url, wait_until='networkidle', timeout=30000)

                        # Get the fully rendered HTML content
                        response_text = page.content()

                        # Use BeautifulSoup to parse the content
                        soup = BeautifulSoup(response_text, 'html.parser')

                        title = soup.title.string.strip() if soup.title and soup.title.string else ""
                        full_content = ' '.join(soup.stripped_strings)

                        contents_list.append(
                            InternetContent(
                                title=title,
                                link=url,
                                full_content=full_content,
                            )
                        )
                    except PlaywrightTimeoutError:
                        logger.error(f"Playwright timed out while loading {url}.")
                    except Exception as e:
                        # This will catch errors like 403 Forbidden or 400 Bad Request
                        logger.error(f"Error processing content from {url} with Playwright: {e}")

                browser.close()

        except Exception as e:
            logger.error(f"Failed to initialize or run Playwright: {e}")

        return contents_list