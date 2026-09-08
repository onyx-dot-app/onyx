from datetime import datetime, timezone
from typing import Any, Optional

import requests

from onyx.configs.app_configs import INDEX_BATCH_SIZE, REQUEST_TIMEOUT_SECONDS
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.rate_limit_wrapper import (
    rate_limit_builder,
)
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import (
    GenerateDocumentsOutput,
    LoadConnector,
    PollConnector,
    SecondsSinceUnixEpoch,
)
from onyx.connectors.models import (
    ConnectorMissingCredentialError,
    Document,
    TextSection,
)
from onyx.utils.retry_wrapper import retry_builder

CLICKUP_API_V3_BASE_URL = "https://api.clickup.com/api/v3"

# Placeholder ClickUp returns for a page whose content the token cannot access.
_NO_ACCESS_CONTENT = "You do not have access to this Doc"

# connector_type (shared with the ClickUp tasks connector) -> Docs API parent_type
_PARENT_TYPE_MAP = {
    "space": "SPACE",
    "folder": "FOLDER",
    "list": "LIST",
    "workspace": "WORKSPACE",
}


class ClickupDocsConnector(LoadConnector, PollConnector):
    """Indexes ClickUp Docs (the knowledge-base feature) via the v3 API.

    One Onyx document is produced per Doc page. Scope is controlled with
    connector_type/connector_ids, mirroring the ClickUp tasks connector.
    """

    def __init__(
        self,
        batch_size: int = INDEX_BATCH_SIZE,
        connector_type: str | None = None,
        connector_ids: list[str] | None = None,
    ) -> None:
        self.batch_size = batch_size
        self.api_token: str | None = None
        self.workspace_id: str | None = None
        self.connector_type = connector_type if connector_type else "workspace"
        self.connector_ids = connector_ids

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self.api_token = credentials["clickup_api_token"]
        self.workspace_id = credentials["clickup_team_id"]
        return None

    @retry_builder()
    @rate_limit_builder(max_calls=100, period=60)
    def _make_request(self, endpoint: str, params: Optional[dict] = None) -> Any:
        if not self.api_token:
            raise ConnectorMissingCredentialError("ClickupDocs")

        response = requests.get(
            f"{CLICKUP_API_V3_BASE_URL}/{endpoint.lstrip('/')}",
            headers={"Authorization": self.api_token},
            params=params,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()

    def _list_docs(self) -> list[dict]:
        """List Docs in the configured scope, following cursor pagination."""
        base_params: dict[str, Any] = {"limit": 50}
        if self.connector_type != "workspace" and self.connector_ids:
            parent_type = _PARENT_TYPE_MAP[self.connector_type]
            parents = [(parent_type, cid) for cid in self.connector_ids]
        else:
            # Whole workspace: no parent filter.
            parents = [(None, None)]

        docs: list[dict] = []
        for parent_type, parent_id in parents:
            cursor: str | None = None
            while True:
                params = dict(base_params)
                if parent_type is not None:
                    params["parent_type"] = parent_type
                    params["parent_id"] = parent_id
                if cursor:
                    params["cursor"] = cursor

                response = self._make_request(
                    f"workspaces/{self.workspace_id}/docs", params
                )
                docs.extend(response.get("docs", []))

                cursor = response.get("next_cursor")
                if not cursor:
                    break
        return docs

    def _iter_pages(self, pages: list[dict]) -> list[dict]:
        """Flatten the (recursively nested) page tree into a flat list."""
        flat: list[dict] = []
        for page in pages:
            flat.append(page)
            children = page.get("pages")
            if children:
                flat.extend(self._iter_pages(children))
        return flat

    def _get_doc_pages(self, doc_id: str) -> list[dict]:
        response = self._make_request(
            f"workspaces/{self.workspace_id}/docs/{doc_id}/pages",
            {"max_page_depth": -1, "content_format": "text/md"},
        )
        # The endpoint returns a list of top-level pages (subpages nested under "pages").
        pages = response if isinstance(response, list) else response.get("pages", [])
        return self._iter_pages(pages)

    def _get_doc(self, doc_id: str) -> dict:
        return self._make_request(f"workspaces/{self.workspace_id}/docs/{doc_id}")

    def _docs_to_index(self) -> list[dict]:
        # Any non-workspace scope must name what to index; otherwise a misconfigured
        # connector would silently fall back to the whole workspace (over-ingestion).
        if self.connector_type != "workspace" and not self.connector_ids:
            raise ConnectorValidationError(
                f"ClickUp Docs '{self.connector_type}' scope requires at least one "
                "id in connector_ids."
            )
        # "doc" scope: connector_ids are Doc IDs indexed directly (skips listing),
        # so a single Doc can be indexed without pulling its whole parent Space.
        if self.connector_type == "doc":
            return [
                {"id": doc_id, "name": self._get_doc(doc_id).get("name", "")}
                for doc_id in self.connector_ids or []
            ]
        return self._list_docs()

    @staticmethod
    def _epoch_ms_to_dt(value: Any) -> datetime | None:
        if value is None:
            return None
        return datetime.fromtimestamp(round(float(value) / 1000, 3), tz=timezone.utc)

    def _fetch_docs_filtered(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> GenerateDocumentsOutput:
        doc_batch: list[Document] = []

        for doc in self._docs_to_index():
            doc_id = doc["id"]
            doc_name = doc.get("name", "")
            for page in self._get_doc_pages(doc_id):
                content = (page.get("content") or "").strip()
                if not content or content == _NO_ACCESS_CONTENT:
                    continue

                updated_at = self._epoch_ms_to_dt(page.get("date_updated"))
                if start is not None and updated_at is not None:
                    if updated_at.timestamp() < start or updated_at.timestamp() > (
                        end if end is not None else updated_at.timestamp()
                    ):
                        continue

                page_id = page["id"]
                page_name = page.get("name") or doc_name or "Untitled"
                link = (
                    f"https://app.clickup.com/{self.workspace_id}"
                    f"/v/dc/{doc_id}/{page_id}"
                )

                doc_batch.append(
                    Document(
                        id=f"clickup_doc__{doc_id}__{page_id}",
                        source=DocumentSource.CLICKUP_DOCS,
                        semantic_identifier=(
                            f"{doc_name} / {page_name}" if doc_name else page_name
                        ),
                        title=page_name,
                        doc_updated_at=updated_at,
                        doc_created_at=self._epoch_ms_to_dt(page.get("date_created")),
                        sections=[TextSection(link=link, text=content)],
                        metadata={
                            "doc_id": str(doc_id),
                            "doc_name": str(doc_name),
                            "page_id": str(page_id),
                            "workspace_id": str(self.workspace_id),
                        },
                    )
                )

                if len(doc_batch) >= self.batch_size:
                    yield doc_batch
                    doc_batch = []

        if doc_batch:
            yield doc_batch

    def load_from_state(self) -> GenerateDocumentsOutput:
        if self.api_token is None:
            raise ConnectorMissingCredentialError("ClickupDocs")
        return self._fetch_docs_filtered()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        if self.api_token is None:
            raise ConnectorMissingCredentialError("ClickupDocs")
        return self._fetch_docs_filtered(start, end)


if __name__ == "__main__":
    import os

    connector = ClickupDocsConnector(
        connector_type=os.environ.get("clickup_connector_type", "workspace"),
        connector_ids=(
            os.environ["clickup_connector_ids"].split(",")
            if os.environ.get("clickup_connector_ids")
            else None
        ),
    )
    connector.load_credentials(
        {
            "clickup_api_token": os.environ["clickup_api_token"],
            "clickup_team_id": os.environ["clickup_team_id"],
        }
    )
    for batch in connector.load_from_state():
        for document in batch:
            print(document)
