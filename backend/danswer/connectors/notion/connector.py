import time
from collections.abc import Generator
from dataclasses import dataclass
from dataclasses import fields
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import Optional

from retry import retry

from danswer.configs.app_configs import INDEX_BATCH_SIZE
from danswer.configs.app_configs import NOTION_CONNECTOR_ENABLE_RECURSIVE_PAGE_LOOKUP
from danswer.configs.constants import DocumentSource
from danswer.connectors.cross_connector_utils.rate_limit_wrapper import (
    rl_requests,
)
from danswer.connectors.interfaces import GenerateDocumentsOutput
from danswer.connectors.interfaces import LoadConnector
from danswer.connectors.interfaces import PollConnector
from danswer.connectors.interfaces import SecondsSinceUnixEpoch
from danswer.connectors.models import Document
from danswer.connectors.models import Section
from danswer.utils.batching import batch_generator
from danswer.utils.logger import setup_logger

logger = setup_logger()

_NOTION_CALL_TIMEOUT = 30  # 30 seconds


@dataclass
class NotionPage:
    """Represents a Notion Page object"""

    id: str
    created_time: str
    last_edited_time: str
    archived: bool
    properties: dict[str, Any]
    url: str

    def __init__(self, **kwargs: dict[str, Any]) -> None:
        names = set([f.name for f in fields(self)])
        for k, v in kwargs.items():
            if k in names:
                setattr(self, k, v)


@dataclass
class NotionSearchResponse:
    """Represents the response from the Notion Search API"""

    results: list[dict[str, Any]]
    next_cursor: Optional[str]
    has_more: bool = False

    def __init__(self, **kwargs: dict[str, Any]) -> None:
        names = set([f.name for f in fields(self)])
        for k, v in kwargs.items():
            if k in names:
                setattr(self, k, v)


# TODO - Add the ability to optionally limit to specific Notion databases
class NotionConnector(LoadConnector, PollConnector):
    """Notion Page connector that reads all Notion pages
    this integration has been granted access to.

    Arguments:
        batch_size (int): Number of objects to index in a batch
    """

    def __init__(
        self,
        batch_size: int = INDEX_BATCH_SIZE,
        recursive_index_enabled: bool = NOTION_CONNECTOR_ENABLE_RECURSIVE_PAGE_LOOKUP,
        root_page_id: str | None = None,
    ) -> None:
        """Initialize with parameters."""
        self.batch_size = batch_size
        self.headers = {
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28",
        }
        self.indexed_pages: set[str] = set()
        self.root_page_id = root_page_id
        # if enabled, will recursively index child pages as they are found rather
        # relying entirely on the `search` API. We have received reports that the
        # `search` API misses many pages - in those cases, this might need to be
        # turned on. It's not currently known why/when this is required.
        # NOTE: this also removes all benefits polling, since we need to traverse
        # all pages regardless of if they are updated. If the notion workspace is
        # very large, this may not be practical.
        self.recursive_index_enabled = recursive_index_enabled or self.root_page_id

    @retry(tries=3, delay=1, backoff=2)
    def _fetch_child_blocks(
        self, block_id: str, cursor: str | None = None
    ) -> dict[str, Any] | None:
        """Fetch all child blocks via the Notion API."""
        logger.debug(f"Fetching children of block with ID '{block_id}'")
        block_url = f"https://api.notion.com/v1/blocks/{block_id}/children"
        query_params = None if not cursor else {"start_cursor": cursor}
        res = rl_requests.get(
            block_url,
            headers=self.headers,
            params=query_params,
            timeout=_NOTION_CALL_TIMEOUT,
        )
        try:
            res.raise_for_status()
        except Exception as e:
            if res.status_code == 404:
                # this happens when a page is not shared with the integration
                # in this case, we should just ignore the page
                logger.error(
                    f"Unable to access block with ID '{block_id}'. "
                    f"This is likely due to the block not being shared "
                    f"with the Danswer integration. Exact exception:\n\n{e}"
                )
                return None
            logger.exception(f"Error fetching blocks - {res.json()}")
            raise e
        return res.json()

    @retry(tries=3, delay=1, backoff=2)
    def _fetch_page(self, page_id: str) -> NotionPage:
        """Fetch a page from it's ID via the Notion API."""
        logger.debug(f"Fetching page for ID '{page_id}'")
        block_url = f"https://api.notion.com/v1/pages/{page_id}"
        res = rl_requests.get(
            block_url,
            headers=self.headers,
            timeout=_NOTION_CALL_TIMEOUT,
        )
        try:
            res.raise_for_status()
        except Exception as e:
            logger.exception(f"Error fetching page - {res.json()}")
            raise e
        return NotionPage(**res.json())

    @retry(tries=3, delay=1, backoff=2)
    def _fetch_database(
        self, database_id: str, cursor: str | None = None
    ) -> dict[str, Any]:
        """Fetch a database from it's ID via the Notion API."""
        logger.debug(f"Fetching database for ID '{database_id}'")
        block_url = f"https://api.notion.com/v1/databases/{database_id}/query"
        body = None if not cursor else {"start_cursor": cursor}
        res = rl_requests.post(
            block_url,
            headers=self.headers,
            json=body,
            timeout=_NOTION_CALL_TIMEOUT,
        )
        try:
            res.raise_for_status()
        except Exception as e:
            if res.json().get("code") == "object_not_found":
                # this happens when a database is not shared with the integration
                # in this case, we should just ignore the database
                logger.error(
                    f"Unable to access database with ID '{database_id}'. "
                    f"This is likely due to the database not being shared "
                    f"with the Danswer integration. Exact exception:\n{e}"
                )
                return {"results": [], "next_cursor": None}
            logger.exception(f"Error fetching database - {res.json()}")
            raise e
        return res.json()

    def _read_pages_from_database(self, database_id: str) -> list[str]:
        """Returns a list of all page IDs in the database"""
        result_pages: list[str] = []
        cursor = None
        while True:
            data = self._fetch_database(database_id, cursor)

            for result in data["results"]:
                obj_id = result["id"]
                obj_type = result["object"]
                if obj_type == "page":
                    logger.debug(
                        f"Found page with ID '{obj_id}' in database '{database_id}'"
                    )
                    result_pages.append(result["id"])
                elif obj_type == "database":
                    logger.debug(
                        f"Found database with ID '{obj_id}' in database '{database_id}'"
                    )
                    result_pages.extend(self._read_pages_from_database(obj_id))

            if data["next_cursor"] is None:
                break

            cursor = data["next_cursor"]

        return result_pages

    def _read_blocks(
        self, base_block_id: str
    ) -> tuple[list[tuple[str, str]], list[str]]:
        """Reads all child blocks for the specified block"""
        result_lines: list[tuple[str, str]] = []
        child_pages: list[str] = []
        cursor = None
        while True:
            data = self._fetch_child_blocks(base_block_id, cursor)

            # this happens when a block is not shared with the integration
            if data is None:
                return result_lines, child_pages

            for result in data["results"]:
                logger.debug(
                    f"Found child block for block with ID '{base_block_id}': {result}"
                )
                result_block_id = result["id"]
                result_type = result["type"]
                result_obj = result[result_type]

                if result_type == "ai_block":
                    logger.warning(
                        f"Skipping 'ai_block' ('{result_block_id}') for base block '{base_block_id}': "
                        f"Notion API does not currently support reading AI blocks (as of 24/02/09) "
                        f"(discussion: https://github.com/danswer-ai/danswer/issues/1053)"
                    )
                    continue

                if result_type == "unsupported":
                    logger.warning(
                        f"Skipping unsupported block type '{result_type}' "
                        f"('{result_block_id}') for base block '{base_block_id}': "
                        f"(discussion: https://github.com/danswer-ai/danswer/issues/1230)"
                    )
                    continue

                cur_result_text_arr = []
                if "rich_text" in result_obj:
                    for rich_text in result_obj["rich_text"]:
                        # skip if doesn't have text object
                        if "text" in rich_text:
                            text = rich_text["text"]["content"]
                            cur_result_text_arr.append(text)

                if result["has_children"]:
                    if result_type == "child_page":
                        child_pages.append(result_block_id)
                    else:
                        logger.debug(f"Entering sub-block: {result_block_id}")
                        subblock_result_lines, subblock_child_pages = self._read_blocks(
                            result_block_id
                        )
                        logger.debug(f"Finished sub-block: {result_block_id}")
                        result_lines.extend(subblock_result_lines)
                        child_pages.extend(subblock_child_pages)

                if result_type == "child_database" and self.recursive_index_enabled:
                    child_pages.extend(self._read_pages_from_database(result_block_id))

                cur_result_text = "\n".join(cur_result_text_arr)
                if cur_result_text:
                    result_lines.append((cur_result_text, result_block_id))

            if data["next_cursor"] is None:
                break

            cursor = data["next_cursor"]

        return result_lines, child_pages

    def _read_page_title(self, page: NotionPage) -> str:
        """Extracts the title from a Notion page"""
        page_title = None
        for _, prop in page.properties.items():
            if prop["type"] == "title" and len(prop["title"]) > 0:
                page_title = " ".join([t["plain_text"] for t in prop["title"]]).strip()
                break
        if page_title is None:
            page_title = f"Untitled Page [{page.id}]"
        return page_title

    def _read_pages(
        self,
        pages: list[NotionPage],
    ) -> Generator[Document, None, None]:
        """Reads pages for rich text content and generates Documents"""
        all_child_page_ids: list[str] = []
        for page in pages:
            if page.id in self.indexed_pages:
                logger.debug(f"Already indexed page with ID '{page.id}'. Skipping.")
                continue

            logger.info(f"Reading page with ID '{page.id}', with url {page.url}")
            page_blocks, child_page_ids = self._read_blocks(page.id)
            all_child_page_ids.extend(child_page_ids)
            page_title = self._read_page_title(page)
            yield (
                Document(
                    id=page.id,
                    # Will add title to the first section later in processing
                    sections=[Section(link=page.url, text="")]
                    + [
                        Section(
                            link=f"{page.url}#{block_id.replace('-', '')}",
                            text=block_text,
                        )
                        for block_text, block_id in page_blocks
                    ],
                    source=DocumentSource.NOTION,
                    semantic_identifier=page_title,
                    doc_updated_at=datetime.fromisoformat(
                        page.last_edited_time
                    ).astimezone(timezone.utc),
                    metadata={},
                )
            )
            self.indexed_pages.add(page.id)

        if self.recursive_index_enabled and all_child_page_ids:
            # NOTE: checking if page_id is in self.indexed_pages to prevent extra
            # calls to `_fetch_page` for pages we've already indexed
            for child_page_batch_ids in batch_generator(
                all_child_page_ids, batch_size=INDEX_BATCH_SIZE
            ):
                child_page_batch = [
                    self._fetch_page(page_id)
                    for page_id in child_page_batch_ids
                    if page_id not in self.indexed_pages
                ]
                yield from self._read_pages(child_page_batch)

    @retry(tries=3, delay=1, backoff=2)
    def _search_notion(self, query_dict: dict[str, Any]) -> NotionSearchResponse:
        """Search for pages from a Notion database. Includes some small number of
        retries to handle misc, flakey failures."""
        logger.debug(f"Searching for pages in Notion with query_dict: {query_dict}")
        res = rl_requests.post(
            "https://api.notion.com/v1/search",
            headers=self.headers,
            json=query_dict,
            timeout=_NOTION_CALL_TIMEOUT,
        )
        res.raise_for_status()
        return NotionSearchResponse(**res.json())

    def _filter_pages_by_time(
        self,
        pages: list[dict[str, Any]],
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        filter_field: str = "last_edited_time",
    ) -> list[NotionPage]:
        """A helper function to filter out pages outside of a time
        range. This functionality doesn't yet exist in the Notion Search API,
        but when it does, this approach can be deprecated.

        Arguments:
            pages (list[dict]) - Pages to filter
            start (float) - start epoch time to filter from
            end (float) - end epoch time to filter to
            filter_field (str) - the attribute on the page to apply the filter
        """
        filtered_pages: list[NotionPage] = []
        for page in pages:
            compare_time = time.mktime(
                time.strptime(page[filter_field], "%Y-%m-%dT%H:%M:%S.000Z")
            )
            if compare_time > start and compare_time <= end:
                filtered_pages += [NotionPage(**page)]
        return filtered_pages

    def _recursive_load(self) -> Generator[list[Document], None, None]:
        if self.root_page_id is None or not self.recursive_index_enabled:
            raise RuntimeError(
                "Recursive page lookup is not enabled, but we are trying to "
                "recursively load pages. This should never happen."
            )

        logger.info(
            "Recursively loading pages from Notion based on root page with "
            f"ID: {self.root_page_id}"
        )
        pages = [self._fetch_page(page_id=self.root_page_id)]
        yield from batch_generator(self._read_pages(pages), self.batch_size)

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        """Applies integration token to headers"""
        self.headers[
            "Authorization"
        ] = f'Bearer {credentials["notion_integration_token"]}'
        return None

    def load_from_state(self) -> GenerateDocumentsOutput:
        """Loads all page data from a Notion workspace.

        Returns:
            list[Document]: list of documents.
        """
        # TODO: remove once Notion search issue is discovered
        if self.recursive_index_enabled and self.root_page_id:
            yield from self._recursive_load()
            return

        query_dict = {
            "filter": {"property": "object", "value": "page"},
            "page_size": self.batch_size,
        }
        while True:
            db_res = self._search_notion(query_dict)
            pages = [NotionPage(**page) for page in db_res.results]
            yield from batch_generator(self._read_pages(pages), self.batch_size)
            if db_res.has_more:
                query_dict["start_cursor"] = db_res.next_cursor
            else:
                break

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        """Uses the Notion search API to fetch updated pages
        within a time period.
        Unfortunately the search API doesn't yet support filtering by times,
        so until they add that, we're just going to page through results until,
        we reach ones that are older than our search criteria.
        """
        # TODO: remove once Notion search issue is discovered
        if self.recursive_index_enabled and self.root_page_id:
            yield from self._recursive_load()
            return

        query_dict = {
            "page_size": self.batch_size,
            "sort": {"timestamp": "last_edited_time", "direction": "descending"},
            "filter": {"property": "object", "value": "page"},
        }
        while True:
            db_res = self._search_notion(query_dict)
            pages = self._filter_pages_by_time(
                db_res.results, start, end, filter_field="last_edited_time"
            )
            if len(pages) > 0:
                yield from batch_generator(self._read_pages(pages), self.batch_size)
                if db_res.has_more:
                    query_dict["start_cursor"] = db_res.next_cursor
                else:
                    break
            else:
                break


if __name__ == "__main__":
    import os

    root_page_id = os.environ.get("NOTION_ROOT_PAGE_ID")
    connector = NotionConnector(root_page_id=root_page_id)
    connector.load_credentials(
        {"notion_integration_token": os.environ.get("NOTION_INTEGRATION_TOKEN")}
    )
    document_batches = connector.load_from_state()
    for doc_batch in document_batches:
        for doc in doc_batch:
            print(doc)
