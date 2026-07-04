import os
from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import cast

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.connectors.cross_connector_utils.rate_limit_wrapper import rl_requests
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import ImageSection
from onyx.connectors.models import TextSection
from onyx.utils.logger import setup_logger

logger = setup_logger()

_NUM_RETRIES = 5
_TIMEOUT = 60
_BOARDS_PAGE_LIMIT = 50
_ITEMS_PAGE_LIMIT = 500
_MONDAY_GRAPHQL_URL = "https://api.monday.com/v2"
_MONDAY_API_VERSION = "2025-10"

_ITEM_FIELDS_FRAGMENT = """
fragment ItemFields on Item {
    id
    name
    url
    created_at
    updated_at
    group {
        title
    }
    creator {
        name
        email
    }
    column_values {
        id
        text
        type
        column {
            title
        }
    }
    updates(limit: 50) {
        body
        created_at
        creator {
            name
            email
        }
    }
    assets {
        name
        public_url
        url
    }
}
"""

_LIST_BOARDS_QUERY = """
query MondayListBoards(
    $boardsLimit: Int!
    $page: Int!
    $boardIds: [ID!]
    $workspaceIds: [ID!]
) {
    boards(
        limit: $boardsLimit
        page: $page
        ids: $boardIds
        workspace_ids: $workspaceIds
    ) {
        id
        name
        workspace {
            id
            name
        }
    }
}
"""

_BOARD_ITEMS_PAGE_QUERY = (
    _ITEM_FIELDS_FRAGMENT
    + """
query MondayBoardItemsPage($boardId: ID!, $itemsLimit: Int!) {
    boards(ids: [$boardId]) {
        id
        name
        workspace {
            id
            name
        }
        items_page(limit: $itemsLimit) {
            cursor
            items {
                ...ItemFields
            }
        }
    }
}
"""
)

_NEXT_ITEMS_PAGE_QUERY = (
    _ITEM_FIELDS_FRAGMENT
    + """
query MondayNextItemsPage($cursor: String!, $itemsLimit: Int!) {
    next_items_page(limit: $itemsLimit, cursor: $cursor) {
        cursor
        items {
            ...ItemFields
        }
    }
}
"""
)

_VALIDATE_QUERY = """
query MondayValidate {
    me {
        id
    }
}
"""


def _normalize_id_filter(ids: list[str] | None) -> list[str] | None:
    if not ids:
        return None
    return ids


def _item_in_time_window(
    updated_at_str: str | None,
    start: datetime | None,
    end: datetime | None,
) -> bool:
    if start is None and end is None:
        return True
    if not updated_at_str:
        return False

    updated_at = time_str_to_utc(updated_at_str)
    if start is not None and updated_at < start:
        return False
    if end is not None and updated_at > end:
        return False
    return True


def _render_column_values(column_values: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for column_value in column_values:
        column_title = (column_value.get("column") or {}).get(
            "title"
        ) or column_value.get("id", "")
        text = column_value.get("text") or ""
        if text:
            lines.append(f"{column_title}: {text}")
    return "\n".join(lines)


def _render_assets(assets: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for asset in assets:
        name = asset.get("name") or "file"
        url = asset.get("public_url") or asset.get("url") or ""
        lines.append(f"{name}: {url}" if url else name)
    return "\n".join(lines)


def _column_metadata(column_values: list[dict[str, Any]]) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for column_value in column_values:
        column_title = (column_value.get("column") or {}).get("title")
        if not column_title:
            continue
        text = column_value.get("text")
        if text:
            metadata[column_title] = str(text)
    return metadata


class MondayConnector(LoadConnector, PollConnector):
    def __init__(
        self,
        board_ids: list[str] | None = None,
        workspace_ids: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.board_ids = board_ids
        self.workspace_ids = workspace_ids
        self.batch_size = batch_size
        self.monday_api_token: str | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        if "monday_api_token" not in credentials:
            raise ConnectorMissingCredentialError("Monday")

        self.monday_api_token = cast(str, credentials["monday_api_token"])
        return None

    def _headers(self) -> dict[str, str]:
        if self.monday_api_token is None:
            raise ConnectorMissingCredentialError("Monday")

        return {
            "Authorization": self.monday_api_token,
            "API-Version": _MONDAY_API_VERSION,
            "Content-Type": "application/json",
        }

    def _run_query(
        self, query: str, variables: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if self.monday_api_token is None:
            raise ConnectorMissingCredentialError("Monday")

        request_body: dict[str, Any] = {"query": query}
        if variables is not None:
            request_body["variables"] = variables

        for attempt in range(_NUM_RETRIES):
            try:
                response = rl_requests.post(
                    _MONDAY_GRAPHQL_URL,
                    headers=self._headers(),
                    json=request_body,
                    timeout=_TIMEOUT,
                )
                if response.status_code == 401:
                    raise CredentialExpiredError(
                        "Invalid monday.com API token (HTTP 401)."
                    )
                if response.status_code == 403:
                    raise InsufficientPermissionsError(
                        "Insufficient permissions for monday.com API (HTTP 403)."
                    )
                if not response.ok:
                    raise RuntimeError(
                        f"Error querying monday.com API (status={response.status_code}): "
                        f"{response.text}"
                    )

                response_json = response.json()
                if errors := response_json.get("errors"):
                    error_messages = "; ".join(
                        str(error.get("message", error)) for error in errors
                    )
                    raise RuntimeError(f"monday.com GraphQL error: {error_messages}")

                data = response_json.get("data")
                if data is None:
                    raise RuntimeError(
                        f"monday.com GraphQL response missing data: {response_json}"
                    )
                return cast(dict[str, Any], data)
            except (CredentialExpiredError, InsufficientPermissionsError):
                raise
            except Exception as exc:
                if attempt == _NUM_RETRIES - 1:
                    raise exc
                logger.warning(
                    "A monday.com GraphQL error occurred: %s. Retrying...", exc
                )

        raise RuntimeError(
            "Unexpected execution when querying monday.com. This should never happen."
        )

    def validate_connector_settings(self) -> None:
        if self.monday_api_token is None:
            raise ConnectorMissingCredentialError("Monday")

        try:
            data = self._run_query(_VALIDATE_QUERY)
            if not data.get("me", {}).get("id"):
                raise ConnectorValidationError(
                    "monday.com validation query did not return a user id."
                )
        except (CredentialExpiredError, InsufficientPermissionsError):
            raise
        except ConnectorMissingCredentialError:
            raise
        except Exception as exc:
            raise ConnectorValidationError(
                f"Unexpected error while validating monday.com connector settings: {exc}"
            ) from exc

    def _build_document(
        self,
        item: dict[str, Any],
        board_name: str,
        workspace_name: str,
    ) -> Document:
        item_id = str(item["id"])
        item_name = item.get("name") or f"Item {item_id}"
        item_url = item.get("url") or f"monday__{item_id}"

        column_values = item.get("column_values") or []
        assets = item.get("assets") or []
        group_title = (item.get("group") or {}).get("title")

        body_parts = [item_name]
        column_text = _render_column_values(column_values)
        if column_text:
            body_parts.append(column_text)
        asset_text = _render_assets(assets)
        if asset_text:
            body_parts.append(asset_text)

        sections: list[TextSection | ImageSection] = [
            TextSection(link=item_url, text="\n\n".join(body_parts))
        ]

        for update in item.get("updates") or []:
            update_body = update.get("body") or ""
            if update_body:
                sections.append(TextSection(link=item_url, text=update_body))

        creator = item.get("creator") or {}
        primary_owners: list[BasicExpertInfo] | None = None
        if creator.get("name") or creator.get("email"):
            primary_owners = [
                BasicExpertInfo(
                    display_name=creator.get("name"),
                    email=creator.get("email"),
                )
            ]

        asset_urls = [
            str(url)
            for asset in assets
            if (url := asset.get("public_url") or asset.get("url"))
        ]

        metadata: dict[str, str] = {
            k: str(v)
            for k, v in {
                "board_name": board_name,
                "group": group_title,
                "created_at": item.get("created_at"),
                "updated_at": item.get("updated_at"),
                "assets": ", ".join(asset_urls) if asset_urls else None,
                **_column_metadata(column_values),
            }.items()
            if v is not None and str(v)
        }

        return Document(
            id=item_url,
            sections=cast(list[TextSection | ImageSection], sections),
            source=DocumentSource.MONDAY,
            semantic_identifier=item_name,
            title=item_name,
            doc_updated_at=time_str_to_utc(item.get("updated_at"))
            if item.get("updated_at")
            else None,
            primary_owners=primary_owners,
            doc_metadata={
                "hierarchy": {
                    "source_path": [workspace_name, board_name],
                    "board_name": board_name,
                }
            },
            metadata=metadata,
        )

    def _append_items_to_batch(
        self,
        items: list[dict[str, Any]],
        board_name: str,
        workspace_name: str,
        start: datetime | None,
        end: datetime | None,
        batch: list[Document],
    ) -> Generator[list[Document], None, list[Document]]:
        for item in items:
            if not _item_in_time_window(item.get("updated_at"), start, end):
                continue

            batch.append(
                self._build_document(
                    item=item,
                    board_name=board_name,
                    workspace_name=workspace_name,
                )
            )
            if len(batch) >= self.batch_size:
                yield batch
                batch = []

        return batch

    def _process_board_items(
        self,
        board_id: str,
        board_name: str,
        workspace_name: str,
        start: datetime | None,
        end: datetime | None,
        batch: list[Document],
    ) -> Generator[list[Document], None, list[Document]]:
        board_response = self._run_query(
            _BOARD_ITEMS_PAGE_QUERY,
            {"boardId": board_id, "itemsLimit": _ITEMS_PAGE_LIMIT},
        ).get("boards", [])
        if not board_response:
            logger.warning("monday.com board %s was not returned by the API", board_id)
            return batch

        board = board_response[0]

        items_page = board.get("items_page") or {}
        items = items_page.get("items") or []
        batch = yield from self._append_items_to_batch(
            items=items,
            board_name=board_name,
            workspace_name=workspace_name,
            start=start,
            end=end,
            batch=batch,
        )

        cursor = items_page.get("cursor")
        while cursor:
            next_page = self._run_query(
                _NEXT_ITEMS_PAGE_QUERY,
                {"cursor": cursor, "itemsLimit": _ITEMS_PAGE_LIMIT},
            )["next_items_page"]
            items = next_page.get("items") or []
            batch = yield from self._append_items_to_batch(
                items=items,
                board_name=board_name,
                workspace_name=workspace_name,
                start=start,
                end=end,
                batch=batch,
            )
            cursor = next_page.get("cursor")

        return batch

    def _process_items(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> GenerateDocumentsOutput:
        if self.monday_api_token is None:
            raise ConnectorMissingCredentialError("Monday")

        board_ids = _normalize_id_filter(self.board_ids)
        workspace_ids = _normalize_id_filter(self.workspace_ids)
        page = 1
        batch: list[Document] = []

        while True:
            variables: dict[str, Any] = {
                "boardsLimit": _BOARDS_PAGE_LIMIT,
                "page": page,
                "boardIds": board_ids,
                "workspaceIds": workspace_ids,
            }
            boards = self._run_query(_LIST_BOARDS_QUERY, variables).get("boards", [])
            if not boards:
                break

            for board in boards:
                board_id = str(board["id"])
                board_name = board.get("name") or f"Board {board_id}"
                workspace_name = (board.get("workspace") or {}).get(
                    "name"
                ) or "Workspace"
                batch = yield from self._process_board_items(
                    board_id=board_id,
                    board_name=board_name,
                    workspace_name=workspace_name,
                    start=start,
                    end=end,
                    batch=batch,
                )

            if board_ids:
                break
            if len(boards) < _BOARDS_PAGE_LIMIT:
                break
            page += 1

        if batch:
            yield batch

    def load_from_state(self) -> GenerateDocumentsOutput:
        yield from self._process_items()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        start_time = datetime.fromtimestamp(start, tz=timezone.utc)
        end_time = datetime.fromtimestamp(end, tz=timezone.utc)
        yield from self._process_items(start=start_time, end=end_time)


if __name__ == "__main__":
    connector = MondayConnector()
    connector.load_credentials({"monday_api_token": os.environ["MONDAY_API_TOKEN"]})
    connector.validate_connector_settings()
    print(next(connector.load_from_state()))
