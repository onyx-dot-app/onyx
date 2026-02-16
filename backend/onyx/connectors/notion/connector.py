import re
from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import cast
from typing import Optional
from urllib.parse import parse_qs
from urllib.parse import urlparse

import requests
from pydantic import BaseModel
from retry import retry
from typing_extensions import override

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.app_configs import NOTION_CONNECTOR_DISABLE_RECURSIVE_PAGE_LOOKUP
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.rate_limit_wrapper import (
    rl_requests,
)
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.exceptions import UnexpectedValidationError
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import NormalizationResult
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import HierarchyNode
from onyx.connectors.models import ImageSection
from onyx.connectors.models import TextSection
from onyx.db.enums import HierarchyNodeType
from onyx.utils.batching import batch_generator
from onyx.utils.logger import setup_logger

logger = setup_logger()

_NOTION_PAGE_SIZE = 100
_NOTION_CALL_TIMEOUT = 30  # 30 seconds
_MAX_PAGES = 1000


# TODO: Tables need to be ingested, Pages need to have their metadata ingested


class NotionPage(BaseModel):
    """Represents a Notion Page object"""

    id: str
    created_time: str
    last_edited_time: str
    archived: bool
    properties: dict[str, Any]
    url: str

    database_name: str | None = None  # Only applicable to the database type page (wiki)
    parent: dict[str, Any] | None = (
        None  # Raw parent object from API for hierarchy tracking
    )


class NotionBlock(BaseModel):
    """Represents a Notion Block object"""

    id: str  # Used for the URL
    text: str
    # In a plaintext representation of the page, how this block should be joined
    # with the existing text up to this point, separated out from text for clarity
    prefix: str


class NotionSearchResponse(BaseModel):
    """Represents the response from the Notion Search API"""

    results: list[dict[str, Any]]
    next_cursor: Optional[str]
    has_more: bool = False


class BlockReadOutput(BaseModel):
    """Output from reading blocks of a page."""

    blocks: list[NotionBlock]
    child_page_ids: list[str]
    hierarchy_nodes: list[HierarchyNode]


class NotionConnector(LoadConnector, PollConnector):
    """Notion Page connector that reads all Notion pages
    this integration has been granted access to.

    Arguments:
        batch_size (int): Number of objects to index in a batch
    """

    def __init__(
        self,
        batch_size: int = INDEX_BATCH_SIZE,
        recursive_index_enabled: bool = not NOTION_CONNECTOR_DISABLE_RECURSIVE_PAGE_LOOKUP,
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

        # Hierarchy tracking state
        self.seen_hierarchy_node_raw_ids: set[str] = set()
        self.workspace_id: str | None = None
        self.workspace_name: str | None = None
        # Maps child page IDs to their containing page ID (discovered in _read_blocks).
        # Used to resolve block_id parent types to the actual containing page.
        self._child_page_parent_map: dict[str, str] = {}

    @classmethod
    @override
    def normalize_url(cls, url: str) -> NormalizationResult:
        """Normalize a Notion URL to extract the page ID (UUID format)."""
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()

        if not ("notion.so" in netloc or "notion.site" in netloc):
            return NormalizationResult(normalized_url=None, use_default=False)

        # Extract page ID from path (format: "Title-PageID")
        path_last = parsed.path.split("/")[-1]
        candidate = path_last.split("-")[-1] if "-" in path_last else path_last

        # Clean and format as UUID
        candidate = re.sub(r"[^0-9a-fA-F-]", "", candidate)
        cleaned = candidate.replace("-", "")

        if len(cleaned) == 32 and re.fullmatch(r"[0-9a-fA-F]{32}", cleaned):
            normalized_uuid = (
                f"{cleaned[0:8]}-{cleaned[8:12]}-{cleaned[12:16]}-"
                f"{cleaned[16:20]}-{cleaned[20:]}"
            ).lower()
            return NormalizationResult(
                normalized_url=normalized_uuid, use_default=False
            )

        # Try query params
        params = parse_qs(parsed.query)
        for key in ("p", "page_id"):
            if key in params and params[key]:
                candidate = params[key][0].replace("-", "")
                if len(candidate) == 32 and re.fullmatch(r"[0-9a-fA-F]{32}", candidate):
                    normalized_uuid = (
                        f"{candidate[0:8]}-{candidate[8:12]}-{candidate[12:16]}-"
                        f"{candidate[16:20]}-{candidate[20:]}"
                    ).lower()
                    return NormalizationResult(
                        normalized_url=normalized_uuid, use_default=False
                    )

        return NormalizationResult(normalized_url=None, use_default=False)

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
                    f"with the Onyx integration. Exact exception:\n\n{e}"
                )
            else:
                logger.exception(
                    f"Error fetching blocks with status code {res.status_code}: {res.json()}"
                )

            # This can occasionally happen, the reason is unknown and cannot be reproduced on our internal Notion
            # Assuming this will not be a critical loss of data
            return None
        return res.json()

    @retry(tries=3, delay=1, backoff=2)
    def _fetch_page(self, page_id: str) -> NotionPage:
        """Fetch a page from its ID via the Notion API, retry with database if page fetch fails."""
        logger.debug(f"Fetching page for ID '{page_id}'")
        page_url = f"https://api.notion.com/v1/pages/{page_id}"
        res = rl_requests.get(
            page_url,
            headers=self.headers,
            timeout=_NOTION_CALL_TIMEOUT,
        )
        try:
            res.raise_for_status()
        except Exception as e:
            logger.warning(
                f"Failed to fetch page, trying database for ID '{page_id}'. Exception: {e}"
            )
            # Try fetching as a database if page fetch fails, this happens if the page is set to a wiki
            # it becomes a database from the notion perspective
            return self._fetch_database_as_page(page_id)
        return NotionPage(**res.json())

    @retry(tries=3, delay=1, backoff=2)
    def _fetch_database_as_page(self, database_id: str) -> NotionPage:
        """Attempt to fetch a database as a page."""
        logger.debug(f"Fetching database for ID '{database_id}' as a page")
        database_url = f"https://api.notion.com/v1/databases/{database_id}"
        res = rl_requests.get(
            database_url,
            headers=self.headers,
            timeout=_NOTION_CALL_TIMEOUT,
        )
        try:
            res.raise_for_status()
        except Exception as e:
            logger.exception(f"Error fetching database as page - {res.json()}")
            raise e
        db_data = res.json()
        database_name = db_data.get("title")
        database_name = (
            database_name[0].get("text", {}).get("content") if database_name else None
        )

        return NotionPage(**db_data, database_name=database_name)

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
            json_data = res.json()
            code = json_data.get("code")
            # Sep 3 2025 backend changed the error message for this case
            # TODO: it is also now possible for there to be multiple data sources per database; at present we
            # just don't handle that. We will need to upgrade the API to the current version + query the
            # new data sources endpoint to handle that case correctly.
            if code == "object_not_found" or (
                code == "validation_error"
                and "does not contain any data sources" in json_data.get("message", "")
            ):
                # this happens when a database is not shared with the integration
                # in this case, we should just ignore the database
                logger.error(
                    f"Unable to access database with ID '{database_id}'. "
                    f"This is likely due to the database not being shared "
                    f"with the Onyx integration. Exact exception:\n{e}"
                )
                return {"results": [], "next_cursor": None}
            logger.exception(f"Error fetching database - {res.json()}")
            raise e
        return res.json()

    @retry(tries=3, delay=1, backoff=2)
    def _fetch_workspace_info(self) -> tuple[str, str]:
        """Fetch workspace ID and name from the bot user endpoint."""
        res = rl_requests.get(
            "https://api.notion.com/v1/users/me",
            headers=self.headers,
            timeout=_NOTION_CALL_TIMEOUT,
        )
        res.raise_for_status()
        data = res.json()
        bot = data.get("bot", {})
        # workspace_id may be in bot object, fallback to user id
        workspace_id = bot.get("workspace_id", data.get("id"))
        workspace_name = bot.get("workspace_name", "Notion Workspace")
        return workspace_id, workspace_name

    def _get_workspace_hierarchy_node(self) -> HierarchyNode | None:
        """Get the workspace hierarchy node, fetching workspace info if needed.

        Returns None if the workspace node has already been yielded.
        """
        if self.workspace_id is None:
            self.workspace_id, self.workspace_name = self._fetch_workspace_info()

        if self.workspace_id in self.seen_hierarchy_node_raw_ids:
            return None

        self.seen_hierarchy_node_raw_ids.add(self.workspace_id)
        return HierarchyNode(
            raw_node_id=self.workspace_id,
            raw_parent_id=None,  # Parent is SOURCE (auto-created by system)
            display_name=self.workspace_name or "Notion Workspace",
            link=f"https://notion.so/{self.workspace_id.replace('-', '')}",
            node_type=HierarchyNodeType.WORKSPACE,
        )

    def _get_parent_raw_id(
        self, parent: dict[str, Any] | None, page_id: str | None = None
    ) -> str | None:
        """Get the parent raw ID for hierarchy tracking.

        Returns workspace_id for top-level pages, or the direct parent ID for nested pages.

        Args:
            parent: The parent object from the Notion API
            page_id: The page's own ID, used to look up block_id parents in our cache
        """
        if not parent:
            return self.workspace_id  # Default to workspace if no parent info

        parent_type = parent.get("type")

        if parent_type == "workspace":
            return self.workspace_id
        elif parent_type == "block_id":
            # Inline page in a block - resolve to the containing page if we discovered it
            if page_id and page_id in self._child_page_parent_map:
                return self._child_page_parent_map[page_id]
            # Fallback to workspace if we don't know the parent
            return self.workspace_id
        elif parent_type == "data_source_id":
            # Newer Notion API may use data_source_id for databases
            return parent.get("database_id") or parent.get("data_source_id")
        elif parent_type in ["page_id", "database_id"]:
            return parent.get(parent_type)

        return self.workspace_id

    def _maybe_yield_hierarchy_node(
        self,
        raw_node_id: str,
        raw_parent_id: str | None,
        display_name: str,
        link: str | None,
        node_type: HierarchyNodeType,
    ) -> HierarchyNode | None:
        """Create and return a hierarchy node if not already yielded.

        Args:
            raw_node_id: The raw ID of the node
            raw_parent_id: The raw ID of the parent node
            display_name: Human-readable name
            link: URL to the node in Notion
            node_type: Type of hierarchy node

        Returns:
            HierarchyNode if new, None if already yielded
        """
        if raw_node_id in self.seen_hierarchy_node_raw_ids:
            return None
        self.seen_hierarchy_node_raw_ids.add(raw_node_id)
        return HierarchyNode(
            raw_node_id=raw_node_id,
            raw_parent_id=raw_parent_id,
            display_name=display_name,
            link=link,
            node_type=node_type,
        )

    @staticmethod
    def _properties_to_str(properties: dict[str, Any]) -> str:
        """Converts Notion properties to a string"""

        def _recurse_list_properties(inner_list: list[Any]) -> str | None:
            list_properties: list[str | None] = []
            for item in inner_list:
                if item and isinstance(item, dict):
                    list_properties.append(_recurse_properties(item))
                elif item and isinstance(item, list):
                    list_properties.append(_recurse_list_properties(item))
                else:
                    list_properties.append(str(item))
            return (
                ", ".join(
                    [
                        list_property
                        for list_property in list_properties
                        if list_property
                    ]
                )
                or None
            )

        def _recurse_properties(inner_dict: dict[str, Any]) -> str | None:
            sub_inner_dict: dict[str, Any] | list[Any] | str = inner_dict
            while isinstance(sub_inner_dict, dict) and "type" in sub_inner_dict:
                type_name = sub_inner_dict["type"]
                sub_inner_dict = sub_inner_dict[type_name]

                # If the innermost layer is None, the value is not set
                if not sub_inner_dict:
                    return None

            # TODO there may be more types to handle here
            if isinstance(sub_inner_dict, list):
                return _recurse_list_properties(sub_inner_dict)
            elif isinstance(sub_inner_dict, str):
                # For some objects the innermost value could just be a string, not sure what causes this
                return sub_inner_dict
            elif isinstance(sub_inner_dict, dict):
                if "name" in sub_inner_dict:
                    return sub_inner_dict["name"]
                if "content" in sub_inner_dict:
                    return sub_inner_dict["content"]
                start = sub_inner_dict.get("start")
                end = sub_inner_dict.get("end")
                if start is not None:
                    if end is not None:
                        return f"{start} - {end}"
                    return start
                elif end is not None:
                    return f"Until {end}"

                if "id" in sub_inner_dict:
                    # This is not useful to index, it's a reference to another Notion object
                    # and this ID value in plaintext is useless outside of the Notion context
                    logger.debug("Skipping Notion object id field property")
                    return None

            logger.debug(f"Unreadable property from innermost prop: {sub_inner_dict}")
            return None

        result = ""
        for prop_name, prop in properties.items():
            if not prop or not isinstance(prop, dict):
                continue

            try:
                inner_value = _recurse_properties(prop)
            except Exception as e:
                # This is not a critical failure, these properties are not the actual contents of the page
                # more similar to metadata
                logger.warning(f"Error recursing properties for {prop_name}: {e}")
                continue
            # Not a perfect way to format Notion database tables but there's no perfect representation
            # since this must be represented as plaintext
            if inner_value:
                result += f"{prop_name}: {inner_value}\t"

        return result

    def _read_pages_from_database(
        self,
        database_id: str,
        database_parent_raw_id: str | None = None,
        database_name: str | None = None,
    ) -> BlockReadOutput:
        """Returns blocks, page IDs, and hierarchy nodes from a database.

        Args:
            database_id: The ID of the database
            database_parent_raw_id: The raw ID of the database's parent (containing page or workspace)
            database_name: The name of the database (from child_database block title)
        """
        result_blocks: list[NotionBlock] = []
        result_pages: list[str] = []
        hierarchy_nodes: list[HierarchyNode] = []

        # Create hierarchy node for this database if not already yielded.
        # Notion URLs omit dashes from UUIDs: https://notion.so/17ab3186873d418fb899c3f6a43f68de
        db_node = self._maybe_yield_hierarchy_node(
            raw_node_id=database_id,
            raw_parent_id=database_parent_raw_id or self.workspace_id,
            display_name=database_name or f"Database {database_id}",
            link=f"https://notion.so/{database_id.replace('-', '')}",
            node_type=HierarchyNodeType.DATABASE,
        )
        if db_node:
            hierarchy_nodes.append(db_node)

        cursor = None
        while True:
            data = self._fetch_database(database_id, cursor)

            for result in data["results"]:
                obj_id = result["id"]
                obj_type = result["object"]
                text = self._properties_to_str(result.get("properties", {}))
                if text:
                    result_blocks.append(NotionBlock(id=obj_id, text=text, prefix="\n"))

                if self.recursive_index_enabled:
                    if obj_type == "page":
                        logger.debug(
                            f"Found page with ID '{obj_id}' in database '{database_id}'"
                        )
                        result_pages.append(result["id"])
                    elif obj_type == "database":
                        logger.debug(
                            f"Found database with ID '{obj_id}' in database '{database_id}'"
                        )
                        # Get nested database name from properties if available
                        nested_db_title = result.get("title", [])
                        nested_db_name = None
                        if nested_db_title and len(nested_db_title) > 0:
                            nested_db_name = (
                                nested_db_title[0].get("text", {}).get("content")
                            )
                        nested_output = self._read_pages_from_database(
                            obj_id,
                            database_parent_raw_id=database_id,
                            database_name=nested_db_name,
                        )
                        result_pages.extend(nested_output.child_page_ids)
                        hierarchy_nodes.extend(nested_output.hierarchy_nodes)

            if data["next_cursor"] is None:
                break

            cursor = data["next_cursor"]

        return BlockReadOutput(
            blocks=result_blocks,
            child_page_ids=result_pages,
            hierarchy_nodes=hierarchy_nodes,
        )

    def _read_blocks(
        self, base_block_id: str, containing_page_id: str | None = None
    ) -> BlockReadOutput:
        """Reads all child blocks for the specified block.

        Args:
            base_block_id: The block ID to read children from
            containing_page_id: The ID of the page that contains this block tree.
                Used to correctly map child pages/databases to their parent page
                rather than intermediate block IDs.
        """
        # If no containing_page_id provided, assume base_block_id is the page itself
        page_id = containing_page_id or base_block_id
        result_blocks: list[NotionBlock] = []
        child_pages: list[str] = []
        hierarchy_nodes: list[HierarchyNode] = []
        cursor = None
        while True:
            data = self._fetch_child_blocks(base_block_id, cursor)

            # this happens when a block is not shared with the integration
            if data is None:
                return BlockReadOutput(
                    blocks=result_blocks,
                    child_page_ids=child_pages,
                    hierarchy_nodes=hierarchy_nodes,
                )

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
                        f"(discussion: https://github.com/onyx-dot-app/onyx/issues/1053)"
                    )
                    continue

                if result_type == "unsupported":
                    logger.warning(
                        f"Skipping unsupported block type '{result_type}' "
                        f"('{result_block_id}') for base block '{base_block_id}': "
                        f"(discussion: https://github.com/onyx-dot-app/onyx/issues/1230)"
                    )
                    continue

                if result_type == "external_object_instance_page":
                    logger.warning(
                        f"Skipping 'external_object_instance_page' ('{result_block_id}') for base block '{base_block_id}': "
                        f"Notion API does not currently support reading external blocks (as of 24/07/03) "
                        f"(discussion: https://github.com/onyx-dot-app/onyx/issues/1761)"
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
                        # Child pages will not be included at this top level, it will be a separate document.
                        # Track parent page so we can resolve block_id parents later.
                        # Use page_id (not base_block_id) to ensure we map to the containing page,
                        # not an intermediate block like a toggle or callout.
                        child_pages.append(result_block_id)
                        self._child_page_parent_map[result_block_id] = page_id
                    else:
                        logger.debug(f"Entering sub-block: {result_block_id}")
                        sub_output = self._read_blocks(result_block_id, page_id)
                        logger.debug(f"Finished sub-block: {result_block_id}")
                        result_blocks.extend(sub_output.blocks)
                        child_pages.extend(sub_output.child_page_ids)
                        hierarchy_nodes.extend(sub_output.hierarchy_nodes)

                if result_type == "child_database":
                    # Extract database name from the child_database block
                    db_title = result_obj.get("title", "")
                    db_output = self._read_pages_from_database(
                        result_block_id,
                        database_parent_raw_id=page_id,  # Parent is the containing page
                        database_name=db_title or None,
                    )
                    # A database on a page often looks like a table, we need to include it for the contents
                    # of the page but the children (cells) should be processed as other Documents
                    result_blocks.extend(db_output.blocks)
                    hierarchy_nodes.extend(db_output.hierarchy_nodes)

                    if self.recursive_index_enabled:
                        child_pages.extend(db_output.child_page_ids)

                if cur_result_text_arr:
                    new_block = NotionBlock(
                        id=result_block_id,
                        text="\n".join(cur_result_text_arr),
                        prefix="\n",
                    )
                    result_blocks.append(new_block)

            if data["next_cursor"] is None:
                break

            cursor = data["next_cursor"]

        return BlockReadOutput(
            blocks=result_blocks,
            child_page_ids=child_pages,
            hierarchy_nodes=hierarchy_nodes,
        )

    def _read_page_title(self, page: NotionPage) -> str | None:
        """Extracts the title from a Notion page"""
        page_title = None
        if hasattr(page, "database_name") and page.database_name:
            return page.database_name
        for _, prop in page.properties.items():
            if prop["type"] == "title" and len(prop["title"]) > 0:
                page_title = " ".join([t["plain_text"] for t in prop["title"]]).strip()
                break

        return page_title

    def _read_pages(
        self,
        pages: list[NotionPage],
    ) -> Generator[Document | HierarchyNode, None, None]:
        """Reads pages for rich text content and generates Documents and HierarchyNodes

        Note that a page which is turned into a "wiki" becomes a database but both top level pages and top level databases
        do not seem to have any properties associated with them.

        Pages that are part of a database can have properties which are like the values of the row in the "database" table
        in which they exist

        This is not clearly outlined in the Notion API docs but it is observable empirically.
        https://developers.notion.com/docs/working-with-page-content
        """
        all_child_page_ids: list[str] = []
        for page in pages:
            if page.id in self.indexed_pages:
                logger.debug(f"Already indexed page with ID '{page.id}'. Skipping.")
                continue

            logger.info(f"Reading page with ID '{page.id}', with url {page.url}")
            block_output = self._read_blocks(page.id)
            all_child_page_ids.extend(block_output.child_page_ids)

            # okay to mark here since there's no way for this to not succeed
            # without a critical failure
            self.indexed_pages.add(page.id)

            raw_page_title = self._read_page_title(page)
            page_title = raw_page_title or f"Untitled Page with ID {page.id}"
            parent_raw_id = self._get_parent_raw_id(page.parent, page_id=page.id)

            # If this page has children (pages or databases), yield it as a hierarchy node FIRST
            # This ensures parent nodes are created before child documents reference them
            if block_output.child_page_ids or block_output.hierarchy_nodes:
                hierarchy_node = self._maybe_yield_hierarchy_node(
                    raw_node_id=page.id,
                    raw_parent_id=parent_raw_id,
                    display_name=page_title,
                    link=page.url,
                    node_type=HierarchyNodeType.PAGE,
                )
                if hierarchy_node:
                    yield hierarchy_node

            # Yield database hierarchy nodes discovered in this page's blocks
            for db_node in block_output.hierarchy_nodes:
                yield db_node

            if not block_output.blocks:
                if not raw_page_title:
                    logger.warning(
                        f"No blocks OR title found for page with ID '{page.id}'. Skipping."
                    )
                    continue

                logger.debug(f"No blocks found for page with ID '{page.id}'")
                """
                Something like:

                TITLE

                PROP1: PROP1_VALUE
                PROP2: PROP2_VALUE
                """
                text = page_title
                if page.properties:
                    text += "\n\n" + "\n".join(
                        [f"{key}: {value}" for key, value in page.properties.items()]
                    )
                sections = [
                    TextSection(
                        link=f"{page.url}",
                        text=text,
                    )
                ]
            else:
                sections = [
                    TextSection(
                        link=f"{page.url}#{block.id.replace('-', '')}",
                        text=block.prefix + block.text,
                    )
                    for block in block_output.blocks
                ]

            yield (
                Document(
                    id=page.id,
                    sections=cast(list[TextSection | ImageSection], sections),
                    source=DocumentSource.NOTION,
                    semantic_identifier=page_title,
                    doc_updated_at=datetime.fromisoformat(
                        page.last_edited_time
                    ).astimezone(timezone.utc),
                    metadata={},
                    parent_hierarchy_raw_node_id=parent_raw_id,
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

    # The | Document is needed for mypy type checking
    def _yield_database_hierarchy_nodes(
        self,
    ) -> Generator[HierarchyNode | Document, None, None]:
        """Search for all databases and yield hierarchy nodes for each.

        This must be called BEFORE page indexing so that database hierarchy nodes
        exist when pages inside databases reference them as parents.
        """
        query_dict: dict[str, Any] = {
            "filter": {"property": "object", "value": "database"},
            "page_size": _NOTION_PAGE_SIZE,
        }
        pages_seen = 0
        while pages_seen < _MAX_PAGES:
            db_res = self._search_notion(query_dict)
            for db in db_res.results:
                db_id = db["id"]
                # Extract title from the title array
                title_arr = db.get("title", [])
                db_name = None
                if title_arr:
                    db_name = " ".join(
                        t.get("plain_text", "") for t in title_arr
                    ).strip()
                if not db_name:
                    db_name = f"Database {db_id}"

                # Get parent using existing helper
                parent_raw_id = self._get_parent_raw_id(db.get("parent"))

                # Notion URLs omit dashes from UUIDs
                db_url = db.get("url") or f"https://notion.so/{db_id.replace('-', '')}"

                node = self._maybe_yield_hierarchy_node(
                    raw_node_id=db_id,
                    raw_parent_id=parent_raw_id or self.workspace_id,
                    display_name=db_name,
                    link=db_url,
                    node_type=HierarchyNodeType.DATABASE,
                )
                if node:
                    yield node

            if not db_res.has_more:
                break
            query_dict["start_cursor"] = db_res.next_cursor
            pages_seen += 1

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
            # Parse ISO 8601 timestamp and convert to UTC epoch time
            timestamp = page[filter_field].replace(".000Z", "+00:00")
            compare_time = datetime.fromisoformat(timestamp).timestamp()
            if compare_time > start and compare_time <= end:
                filtered_pages += [NotionPage(**page)]
        return filtered_pages

    def _recursive_load(self) -> GenerateDocumentsOutput:
        if self.root_page_id is None or not self.recursive_index_enabled:
            raise RuntimeError(
                "Recursive page lookup is not enabled, but we are trying to "
                "recursively load pages. This should never happen."
            )

        # Yield workspace hierarchy node FIRST before any pages
        workspace_node = self._get_workspace_hierarchy_node()
        if workspace_node:
            yield [workspace_node]

        logger.info(
            "Recursively loading pages from Notion based on root page with "
            f"ID: {self.root_page_id}"
        )
        pages = [self._fetch_page(page_id=self.root_page_id)]
        yield from batch_generator(self._read_pages(pages), self.batch_size)

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        """Applies integration token to headers"""
        self.headers["Authorization"] = (
            f'Bearer {credentials["notion_integration_token"]}'
        )
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

        # Yield workspace hierarchy node FIRST before any pages
        workspace_node = self._get_workspace_hierarchy_node()
        if workspace_node:
            yield [workspace_node]

        # Yield database hierarchy nodes BEFORE pages so parent references resolve
        yield from batch_generator(
            self._yield_database_hierarchy_nodes(), self.batch_size
        )

        query_dict: dict[str, Any] = {
            "filter": {"property": "object", "value": "page"},
            "page_size": _NOTION_PAGE_SIZE,
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

        # Yield workspace hierarchy node FIRST before any pages
        workspace_node = self._get_workspace_hierarchy_node()
        if workspace_node:
            yield [workspace_node]

        # Yield database hierarchy nodes BEFORE pages so parent references resolve.
        # We yield all databases without time filtering because a page's parent
        # database might not have been edited even if the page was.
        yield from batch_generator(
            self._yield_database_hierarchy_nodes(), self.batch_size
        )

        query_dict: dict[str, Any] = {
            "page_size": _NOTION_PAGE_SIZE,
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

    def validate_connector_settings(self) -> None:
        if not self.headers.get("Authorization"):
            raise ConnectorMissingCredentialError("Notion credentials not loaded.")

        try:
            # We'll do a minimal search call (page_size=1) to confirm accessibility
            if self.root_page_id:
                # If root_page_id is set, fetch the specific page
                res = rl_requests.get(
                    f"https://api.notion.com/v1/pages/{self.root_page_id}",
                    headers=self.headers,
                    timeout=_NOTION_CALL_TIMEOUT,
                )
            else:
                # If root_page_id is not set, perform a minimal search
                test_query = {
                    "filter": {"property": "object", "value": "page"},
                    "page_size": 1,
                }
                res = rl_requests.post(
                    "https://api.notion.com/v1/search",
                    headers=self.headers,
                    json=test_query,
                    timeout=_NOTION_CALL_TIMEOUT,
                )
            res.raise_for_status()

        except requests.exceptions.HTTPError as http_err:
            status_code = http_err.response.status_code if http_err.response else None

            if status_code == 401:
                raise CredentialExpiredError(
                    "Notion credential appears to be invalid or expired (HTTP 401)."
                )
            elif status_code == 403:
                raise InsufficientPermissionsError(
                    "Your Notion token does not have sufficient permissions (HTTP 403)."
                )
            elif status_code == 404:
                # Typically means resource not found or not shared. Could be root_page_id is invalid.
                raise ConnectorValidationError(
                    "Notion resource not found or not shared with the integration (HTTP 404)."
                )
            elif status_code == 429:
                raise ConnectorValidationError(
                    "Validation failed due to Notion rate-limits being exceeded (HTTP 429). "
                    "Please try again later."
                )
            else:
                raise UnexpectedValidationError(
                    f"Unexpected Notion HTTP error (status={status_code}): {http_err}"
                ) from http_err

        except Exception as exc:
            raise UnexpectedValidationError(
                f"Unexpected error during Notion settings validation: {exc}"
            )


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
