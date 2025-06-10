"""
This is the XenforoConnector class. It is used to connect to a Xenforo forum and load or update documents from the forum.

To use this class, you need to provide the URL of the Xenforo forum board you want to connect to when creating an instance
of the class. The URL should be a string that starts with 'http://' or 'https://', followed by the domain name of the
forum, followed by the board name. For example:

    base_url = 'https://www.example.com/forum/boards/some-topic/'

The `load_from_state` method is used to load documents from the forum. It takes an optional `state` parameter, which
can be used to specify a state from which to start loading documents.
"""

import re
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from urllib.parse import urlparse

import pytz
import requests
from bs4 import BeautifulSoup
from bs4 import Tag

from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import datetime_to_utc
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.utils.logger import setup_logger

logger = setup_logger()


def get_title(soup: BeautifulSoup) -> str:
    el = soup.find("h1", "p-title-value")
    if not el:
        return ""
    title = el.text
    for char in (";", ":", "!", "*", "/", "\\", "?", '"', "<", ">", "|"):
        title = title.replace(char, "_")
    return title


def get_pages(soup: BeautifulSoup, url: str) -> list[str]:
    page_tags = soup.select("li.pageNav-page")
    page_numbers = []
    for button in page_tags:
        if re.match(r"^\d+$", button.text):
            page_numbers.append(button.text)

    max_pages = int(max(page_numbers, key=int)) if page_numbers else 1

    all_pages = []
    for x in range(1, int(max_pages) + 1):
        all_pages.append(f"{url}page-{x}")
    return all_pages


def parse_post_date(post_element: BeautifulSoup) -> datetime:
    el = post_element.find("time")
    if not isinstance(el, Tag) or "datetime" not in el.attrs:
        return datetime.utcfromtimestamp(0).replace(tzinfo=timezone.utc)

    date_value = el["datetime"]

    # Ensure date_value is a string (if it's a list, take the first element)
    if isinstance(date_value, list):
        date_value = date_value[0]

    post_date = datetime.strptime(date_value, "%Y-%m-%dT%H:%M:%S%z")
    return datetime_to_utc(post_date)


def scrape_page_posts(
    soup: BeautifulSoup,
    page_index: int,
    url: str,
    initial_run: bool,
    start_time: datetime,
) -> list:
    title = get_title(soup)

    documents = []
    for post in soup.find_all("div", class_="message-inner"):
        post_date = parse_post_date(post)
        if initial_run or post_date > start_time:
            el = post.find("div", class_="bbWrapper")
            if not el:
                continue
            post_text = el.get_text(strip=True) + "\n"
            author_tag = post.find("a", class_="username")
            if author_tag is None:
                author_tag = post.find("span", class_="username")
            author = author_tag.get_text(strip=True) if author_tag else "Deleted author"
            formatted_time = post_date.strftime("%Y-%m-%d %H:%M:%S")

            # TODO: if a caller calls this for each page of a thread, it may see the
            # same post multiple times if there is a sticky post
            # that appears on each page of a thread.
            # it's important to generate unique doc id's, so page index is part of the
            # id. We may want to de-dupe this stuff inside the indexing service.
            document = Document(
                id=f"{DocumentSource.XENFORO.value}_{title}_{page_index}_{formatted_time}",
                sections=[TextSection(link=url, text=post_text)],
                title=title,
                source=DocumentSource.XENFORO,
                semantic_identifier=title,
                primary_owners=[BasicExpertInfo(display_name=author)],
                metadata={
                    "type": "post",
                    "author": author,
                    "time": formatted_time,
                },
                doc_updated_at=post_date,
            )

            documents.append(document)
    return documents


class XenforoConnector(LoadConnector):
    # Class variable to track if the connector has been run before
    has_been_run_before = False

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self.initial_run = not XenforoConnector.has_been_run_before
        self.start = datetime.utcnow().replace(tzinfo=pytz.utc) - timedelta(days=1)
        self.cookies: dict[str, str] = {}
        # mimic user browser to avoid being blocked by the website (see: https://www.useragents.me/)
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/121.0.0.0 Safari/537.36"
        }

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        if credentials:
            logger.warning("Unexpected credentials provided for Xenforo Connector")
        return None

    def load_from_state(self) -> GenerateDocumentsOutput:
        # Standardize URL to always end in /.
        if self.base_url[-1] != "/":
            self.base_url += "/"

        # Remove all extra parameters from the end such as page, post.
        matches = ("threads/", "boards/", "forums/")
        for each in matches:
            if each in self.base_url:
                try:
                    self.base_url = self.base_url[
                        0 : self.base_url.index(
                            "/", self.base_url.index(each) + len(each)
                        )
                        + 1
                    ]
                except ValueError:
                    pass

        doc_batch: list[Document] = []
        all_threads = []

        # If the URL contains "boards/" or "forums/", find all threads.
        if "boards/" in self.base_url or "forums/" in self.base_url:
            pages = get_pages(self.requestsite(self.base_url), self.base_url)

            # Get all pages on thread_list_page
            for pre_count, thread_list_page in enumerate(pages, start=1):
                logger.info(
                    f"Getting pages from thread_list_page.. Current: {pre_count}/{len(pages)}\r"
                )
                all_threads += self.get_threads(thread_list_page)
        # If the URL contains "threads/", add the thread to the list.
        elif "threads/" in self.base_url:
            all_threads.append(self.base_url)

        # Process all threads
        for thread_count, thread_url in enumerate(all_threads, start=1):
            soup = self.requestsite(thread_url)
            if soup is None:
                logger.error(f"Failed to load page: {self.base_url}")
                continue
            pages = get_pages(soup, thread_url)
            # Getting all pages for all threads
            for page_index, page in enumerate(pages, start=1):
                logger.info(
                    f"Progress: Page {page_index}/{len(pages)} - Thread {thread_count}/{len(all_threads)}\r"
                )
                soup_page = self.requestsite(page)
                doc_batch.extend(
                    scrape_page_posts(
                        soup_page, page_index, thread_url, self.initial_run, self.start
                    )
                )
            if doc_batch:
                yield doc_batch

        # Mark the initial run finished after all threads and pages have been processed
        XenforoConnector.has_been_run_before = True

    def get_threads(self, url: str) -> list[str]:
        soup = self.requestsite(url)
        thread_tags = soup.find_all(class_="structItem-title")
        base_url = "{uri.scheme}://{uri.netloc}".format(uri=urlparse(url))
        threads = []
        for x in thread_tags:
            y = x.find_all(href=True)
            for element in y:
                link = element["href"]
                if "threads/" in link:
                    stripped = link[0 : link.rfind("/") + 1]
                    if base_url + stripped not in threads:
                        threads.append(base_url + stripped)
        return threads

    def requestsite(self, url: str) -> BeautifulSoup:
        try:
            response = requests.get(
                url, cookies=self.cookies, headers=self.headers, timeout=10
            )
            if response.status_code != 200:
                logger.error(
                    f"<{url}> Request Error: {response.status_code} - {response.reason}"
                )
            return BeautifulSoup(response.text, "html.parser")
        except TimeoutError:
            logger.error("Timed out Error.")
        except Exception as e:
            logger.error(f"Error on {url}")
            logger.exception(e)
        return BeautifulSoup("", "html.parser")


if __name__ == "__main__":
    connector = XenforoConnector(
        # base_url="https://cassiopaea.org/forum/threads/how-to-change-your-emotional-state.41381/"
        base_url="https://xenforo.com/community/threads/whats-new-with-enhanced-search-resource-manager-and-media-gallery-in-xenforo-2-3.220935/"
    )
    document_batches = connector.load_from_state()
    print(next(document_batches))
