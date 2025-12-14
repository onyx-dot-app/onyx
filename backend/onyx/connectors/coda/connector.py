import os
from datetime import datetime, timezone
from collections.abc import Generator
from typing import Any, Dict, List, Optional, cast

from pydantic import BaseModel
from retry import retry

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource

from onyx.connectors.cross_connector_utils.rate_limit_wrapper import (
    rl_requests,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.connectors.interfaces import (
    GenerateDocumentsOutput,
    LoadConnector,
    PollConnector,
    SecondsSinceUnixEpoch,
)
from onyx.connectors.models import (
    ConnectorMissingCredentialError,
    Document,
    ImageSection,
    TextSection,
)

from onyx.utils.batching import batch_generator
from onyx.utils.logger import setup_logger


_CODA_CALL_TIMEOUT = 30
CODA_BASE_URL = "https://coda.io/apis/v1"

logger = setup_logger()

class CodaClientRequestFailedError(ConnectionError):
    def __init__(self, message: str, status_code: int):
        super().__init__(f"Coda API request failed with status {status_code}: {message}")
        self.status_code = status_code


class CodaDoc(BaseModel):
    id: str
    browser_link: str
    name: str
    created_at: str
    updated_at: str
    workspace_id: str
    workspace_name: str
    folder_id: str | None
    folder_name: str | None


class CodaPage(BaseModel):
    id: str
    browser_link: str
    name: str
    content_type: str
    created_at: str
    updated_at: str
    doc_id: str


class CodaTable(BaseModel):
    id: str
    name: str
    browser_link: str
    created_at: str
    updated_at: str
    doc_id: str


class CodaRow(BaseModel):
    id: str
    name: Optional[str] = None
    index: Optional[int] = None
    browser_link: str
    created_at: str
    updated_at: str
    values: Dict[str, Any]
    table_id: str
    doc_id: str


class CodaApiClient:
    def __init__(
        self, 
        bearer_token: str, 
    ) -> None:
        self.bearer_token = bearer_token
        self.base_url = os.environ.get("CODA_BASE_URL", CODA_BASE_URL)  
    
    def get(self, endpoint: str, params: Optional[dict[str, str]] = None) -> dict[str, Any]:
        url = self._build_url(endpoint)
        headers = self._build_headers()

        #although the Coda API is generous with rate limits, we still want to respect them
        response = rl_requests.get(url, headers=headers, params=params, timeout=_CODA_CALL_TIMEOUT)

        try:
            json = response.json()
        except Exception:
            json = {}

        if response.status_code >= 300:
            error = response.reason
            response_error = json.get("error", {}).get("message", "")
            if response_error:
                error = response_error
            raise CodaClientRequestFailedError(error, response.status_code)

        return json

    def _build_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.bearer_token}"}
    
    def _build_url(self, endpoint: str) -> str:
        return self.base_url.rstrip("/") + "/" + endpoint.lstrip("/")


class CodaConnector(LoadConnector, PollConnector):
    def __init__(
        self, 
        batch_size: int = INDEX_BATCH_SIZE,
        index_page_content: bool = True,
        workspace_id: str | None = None,
    ) -> None:
        self.batch_size = batch_size
        self.index_page_content = index_page_content
        self.workspace_id = workspace_id
        self.coda_client: CodaApiClient | None = None

    

    @retry(tries=3, delay=1, backoff=2) 
    def _get_doc(self, doc_id: str) -> CodaDoc:
        """Fetch a specific Coda document by its ID."""
        logger.debug(f"Fetching Coda doc with ID: {doc_id}")
        try:
            response = self.coda_client.get(f"docs/{doc_id}")
        except CodaClientRequestFailedError as e:
            if e.status_code == 404:
                raise ConnectorValidationError(f"Failed to fetch doc: {doc_id}") from e
            else:
                raise

        return CodaDoc(
            id=response["id"],
            browser_link=response["browserLink"],
            name=response["name"],
            created_at=response["createdAt"],
            updated_at=response["updatedAt"],
            workspace_id=response["workspace"]["id"],
            workspace_name=response["workspace"]["name"],
            folder_id=response["folder"]["id"] if response.get("folder") else None,
            folder_name=response["folder"]["name"] if response.get("folder") else None
        )

    @retry(tries=3, delay=1, backoff=2) 
    def _get_page(self, doc_id: str, page_id: str) -> CodaPage:
        """Fetch a specific page from a Coda document."""
        logger.debug(f"Fetching Coda page with ID: {page_id}")
        try:
            response = self.coda_client.get(f"docs/{doc_id}/pages/{page_id}")
        except CodaClientRequestFailedError as e:
            if e.status_code == 404:
                raise ConnectorValidationError(f"Failed to fetch page: {page_id} from doc: {doc_id}") from e
            else:
                raise

        return CodaPage(
            id=response["id"],
            doc_id=doc_id,
            browser_link=response["browserLink"],
            name=response["name"],
            content_type=response["contentType"],
            created_at=response["createdAt"],
            updated_at=response["updatedAt"]
        )

    @retry(tries=3, delay=1, backoff=2) 
    def _get_table(self, doc_id: str, table_id: str) -> CodaTable:
        """Fetch a specific table from a Coda document."""
        logger.debug(f"Fetching Coda table with ID: {table_id}")
        try:
            response = self.coda_client.get(f"docs/{doc_id}/tables/{table_id}")
        except CodaClientRequestFailedError as e:
            if e.status_code == 404:
                raise ConnectorValidationError(f"Failed to fetch table: {table_id} from doc: {doc_id}") from e
            else:
                raise

        return CodaTable(
            id=response["id"],
            name=response["name"],
            browser_link=response["browserLink"],
            created_at=response["createdAt"],
            updated_at=response["updatedAt"],
            doc_id=doc_id
        )
    
    @retry(tries=3, delay=1, backoff=2) 
    def _get_row(self, doc_id: str, table_id: str, row_id: str) -> CodaRow:
        """Fetch a specific row from a Coda table."""
        logger.debug(f"Fetching Coda row with ID: {row_id}")
        try:
            response = self.coda_client.get(f"docs/{doc_id}/tables/{table_id}/rows/{row_id}")
        except CodaClientRequestFailedError as e:
            if e.status_code == 404:
                raise ConnectorValidationError(f"Failed to fetch row: {row_id} from table: {table_id} in doc: {doc_id}") from e
            else:
                raise

        values = {}
        for col_name, col_value in response.get("values", {}).items():
            values[col_name] = col_value

        return CodaRow(
            id=response["id"],
            name=response.get("name"),
            index=response.get("index"),
            browser_link=response["browserLink"],
            created_at=response["createdAt"],
            updated_at=response["updatedAt"],
            values=values,
            table_id=table_id,
            doc_id=doc_id
        )
    
    @retry(tries=3, delay=1, backoff=2)
    def _list_all_docs(
        self,
        endpoint: str = "docs",
        params: Optional[Dict[str, str]] = None
    ) -> List[CodaDoc]:
        """List all Coda documents in the workspace."""
        logger.debug("Listing documents in Coda")
        all_docs: List[CodaDoc] = []
        next_page_token: str | None = None
        params = params or {}
        
        # Filter by workspace_id if specified
        if self.workspace_id:
            params["workspaceId"] = self.workspace_id

        while True:
            if next_page_token:
                params["pageToken"] = next_page_token

            try:
                response = self.coda_client.get(endpoint, params=params)
            except CodaClientRequestFailedError as e:
                if e.status_code == 404:
                    raise ConnectorValidationError("Failed to list docs") from e
                else:
                    raise

            items = response.get("items", [])

            for item in items:
                doc = CodaDoc(
                    id=item["id"],
                    browser_link=item["browserLink"],
                    name=item["name"],
                    created_at=item["createdAt"],
                    updated_at=item["updatedAt"],
                    workspace_id=item["workspace"]["id"],
                    workspace_name=item["workspace"]["name"],
                    folder_id=item["folder"]["id"] if item.get("folder") else None,
                    folder_name=item["folder"]["name"] if item.get("folder") else None
                )
                all_docs.append(doc)

            next_page_token = response.get("nextPageToken")
            if not next_page_token:
                break

        logger.debug(f"Found {len(all_docs)} docs")
        return all_docs
    
    @retry(tries=3, delay=1, backoff=2)
    def _list_pages_in_doc(self, doc_id: str) -> List[CodaPage]:
        """List all pages in a Coda document."""
        logger.debug(f"Listing pages in Coda doc with ID: {doc_id}")
        pages: List[CodaPage] = []
        endpoint = f"docs/{doc_id}/pages"
        params: Dict[str, str] = {}
        next_page_token: str | None = None

        while True:
            if next_page_token:
                params["pageToken"] = next_page_token

            try:
                response = self.coda_client.get(endpoint, params=params)
            except CodaClientRequestFailedError as e:
                if e.status_code == 404:
                    raise ConnectorValidationError(f"Failed to list pages for doc: {doc_id}") from e
                else:
                    raise

            items = response.get("items", [])
            for item in items:
                #can be removed if we don't care to skip hidden pages
                if item.get("isHidden", False):
                    continue

                pages.append(
                    CodaPage(
                        id=item["id"],
                        browser_link=item["browserLink"],
                        name=item["name"],
                        content_type=item["contentType"],
                        created_at=item["createdAt"],
                        updated_at=item["updatedAt"],
                        doc_id=doc_id,
                    )
                )

            next_page_token = response.get("nextPageToken")
            if not next_page_token:
                break

        logger.debug(f"Found {len(pages)} pages in doc {doc_id}")
        return pages

    @retry(tries=3, delay=1, backoff=2)
    def _fetch_page_content(self, doc_id: str, page_id: str) -> str:
        """Fetch the content of a Coda page."""
        logger.debug(f"Fetching content for page {page_id} in doc {doc_id}")
        content_parts = []
        next_page_token: str | None = None
        params: Dict[str, str] = {}
        
        while True:
            if next_page_token:
                params["pageToken"] = next_page_token
            
            try:
                response = self.coda_client.get(f"docs/{doc_id}/pages/{page_id}/content", params=params)
            except CodaClientRequestFailedError as e:
                if e.status_code == 404:
                    logger.debug(f"No content available for page {page_id}")
                    return ""
                raise
            
            items = response.get("items", [])
            
            for item in items:
                item_content = item.get("itemContent", {})
                
                content_text = item_content.get("content", "")
                if content_text:
                    content_parts.append(content_text)
            
            next_page_token = response.get("nextPageToken")
            if not next_page_token:
                break
        
        return "\n\n".join(content_parts)

    @retry(tries=3, delay=1, backoff=2) 
    def _list_tables(self, doc_id: str) -> List[CodaTable]:
        """List all tables in a Coda document."""
        logger.debug(f"Listing tables in Coda doc with ID: {doc_id}")
        tables: List[CodaTable] = []
        endpoint = f"docs/{doc_id}/tables"
        params: Dict[str, str] = {}
        next_page_token: str | None = None

        while True:
            if next_page_token:
                params["pageToken"] = next_page_token

            try:
                response = self.coda_client.get(endpoint, params=params)
            except CodaClientRequestFailedError as e:
                if e.status_code == 404:
                    raise ConnectorValidationError(f"Failed to list tables for doc: {doc_id}") from e
                else:
                    raise

            items = response.get("items", [])
            for item in items:
                tables.append(
                    CodaTable(
                        id=item["id"],
                        browser_link=item["browserLink"],
                        name=item["name"],
                        created_at=item["createdAt"],
                        updated_at=item["updatedAt"],
                        doc_id=doc_id
                    )
                )

            next_page_token = response.get("nextPageToken")
            if not next_page_token:
                break

        logger.debug(f"Found {len(tables)} tables in doc {doc_id}")
        return tables
    
    @retry(tries=3, delay=1, backoff=2) 
    def _list_rows_and_values(self, doc_id: str, table_id: str) -> List[CodaRow]:
        """List all rows and their values in a table."""
        logger.debug(f"Listing rows in Coda table: {table_id} in Coda doc: {doc_id}")
        rows: List[CodaRow] = []
        endpoint = f"docs/{doc_id}/tables/{table_id}/rows"
        params: Dict[str, str] = {"valueFormat": "rich"}
        next_page_token: str | None = None

        while True:
            if next_page_token:
                params["pageToken"] = next_page_token

            try:
                response = self.coda_client.get(endpoint, params=params)
            except CodaClientRequestFailedError as e:
                if e.status_code == 404:
                    raise ConnectorValidationError(f"Failed to list rows for table: {table_id} in doc: {doc_id}") from e
                else:
                    raise

            items = response.get("items", [])
            for item in items:
                values = {}
                for col_name, col_value in item.get("values", {}).items():
                    values[col_name] = col_value

                rows.append(
                    CodaRow(
                        id=item["id"],
                        name=item["name"],
                        index=item["index"],
                        browser_link=item["browserLink"],
                        created_at=item["createdAt"],
                        updated_at=item["updatedAt"],
                        values=values,
                        table_id=table_id,
                        doc_id=doc_id,
                    )
                )

            next_page_token = response.get("nextPageToken")
            if not next_page_token:
                break

        logger.debug(f"Found {len(rows)} rows in table {table_id}")
        return rows

    def _convert_page_to_document(self, page: CodaPage, content: str = "") -> Document:
        """Convert a page into a Document."""
        page_updated = datetime.fromisoformat(page.updated_at).astimezone(timezone.utc)
        
        text_parts = [page.name, page.browser_link]
        if content:
            text_parts.append(content)
        
        sections = [
            TextSection(
                link=page.browser_link,
                text="\n\n".join(text_parts)
            )
        ]
        
        return Document(
            id=f"coda-page-{page.doc_id}-{page.id}",
            sections=cast(list[TextSection | ImageSection], sections),
            source=DocumentSource.CODA,
            semantic_identifier=page.name or f"Page {page.id}",
            doc_updated_at=page_updated,
            metadata={
                "browser_link": page.browser_link,
                "doc_id": page.doc_id,
                "content_type": page.content_type,
            },
        )

    def _convert_table_with_rows_to_document(
        self, table: CodaTable, rows: List[CodaRow]
    ) -> Document:
        """Convert a table and its rows into a single Document with multiple sections (one per row)."""
        table_updated = datetime.fromisoformat(table.updated_at).astimezone(timezone.utc)
        
        sections: List[TextSection] = []
        for row in rows:
            content_text = " ".join(
                str(v) if not isinstance(v, list) else " ".join(map(str, v))
                for v in row.values.values()
            )
            
            row_name = row.name or f"Row {row.index or row.id}"
            text = f"{row_name}: {content_text}" if content_text else row_name
            
            sections.append(
                TextSection(
                    link=row.browser_link,
                    text=text
                )
            )
        
        # If no rows, create a single section for the table itself
        if not sections:
            sections = [
                TextSection(
                    link=table.browser_link,
                    text=f"Table: {table.name}"
                )
            ]
        
        return Document(
            id=f"coda-table-{table.doc_id}-{table.id}",
            sections=cast(list[TextSection | ImageSection], sections),
            source=DocumentSource.CODA,
            semantic_identifier=table.name or f"Table {table.id}",
            doc_updated_at=table_updated,
            metadata={
                "browser_link": table.browser_link,
                "doc_id": table.doc_id,
                "row_count": str(len(rows)),
            },
        )

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        """Load and validate Coda credentials."""
        self.coda_client = CodaApiClient(
            bearer_token=credentials["coda_bearer_token"]
        )

        try:
            self.coda_client.get("docs", params={"limit": "1"})
        except CodaClientRequestFailedError as e:
            if e.status_code == 401:
                raise ConnectorMissingCredentialError("Invalid Coda API token")
            raise

        return None

    def load_from_state(self) -> GenerateDocumentsOutput:
        """Load all documents from Coda workspace."""
        if self.coda_client is None:
            raise ConnectorMissingCredentialError("Coda")

        def _iter_documents() -> Generator[Document, None, None]:
            docs = self._list_all_docs()
            logger.info(f"Found {len(docs)} Coda docs to process")
            
            for doc in docs:
                logger.debug(f"Processing doc: {doc.name} ({doc.id})")
                
                try:
                    pages = self._list_pages_in_doc(doc.id)
                    for page in pages:
                        content = ""
                        if self.index_page_content:
                            try:
                                content = self._fetch_page_content(doc.id, page.id)
                            except Exception as e:
                                logger.warning(f"Failed to fetch content for page {page.id}: {e}")
                        yield self._convert_page_to_document(page, content)
                except ConnectorValidationError as e:
                    logger.warning(f"Failed to list pages for doc {doc.id}: {e}")
                
                try:
                    tables = self._list_tables(doc.id)
                    for table in tables:
                        try:
                            rows = self._list_rows_and_values(doc.id, table.id)
                            yield self._convert_table_with_rows_to_document(table, rows)
                        except ConnectorValidationError as e:
                            logger.warning(f"Failed to list rows for table {table.id}: {e}")
                            # Yield table without rows
                            yield self._convert_table_with_rows_to_document(table, [])
                except ConnectorValidationError as e:
                    logger.warning(f"Failed to list tables for doc {doc.id}: {e}")

        return batch_generator(_iter_documents(), self.batch_size)

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        """
        Polls the Coda API for documents updated between start and end timestamps.
        We refer to page and table update times to determine if they need to be re-indexed.
        """
        if self.coda_client is None:
            raise ConnectorMissingCredentialError("Coda")

        def _iter_documents() -> Generator[Document, None, None]:
            docs = self._list_all_docs()
            logger.info(f"Polling {len(docs)} Coda docs for updates between {start} and {end}")
            
            for doc in docs:
                try:
                    pages = self._list_pages_in_doc(doc.id)
                    for page in pages:
                        page_timestamp = datetime.fromisoformat(page.updated_at).astimezone(timezone.utc).timestamp()
                        if start < page_timestamp <= end:
                            content = ""
                            if self.index_page_content:
                                try:
                                    content = self._fetch_page_content(doc.id, page.id)
                                except Exception as e:
                                    logger.warning(f"Failed to fetch content for page {page.id}: {e}")
                            yield self._convert_page_to_document(page, content)
                except ConnectorValidationError as e:
                    logger.warning(f"Failed to list pages for doc {doc.id}: {e}")
                
                try:
                    tables = self._list_tables(doc.id)
                    for table in tables:
                        table_timestamp = datetime.fromisoformat(table.updated_at).astimezone(timezone.utc).timestamp()
                        
                        try:
                            rows = self._list_rows_and_values(doc.id, table.id)
                            
                            table_or_rows_updated = start < table_timestamp <= end
                            if not table_or_rows_updated:
                                for row in rows:
                                    row_timestamp = datetime.fromisoformat(row.updated_at).astimezone(timezone.utc).timestamp()
                                    if start < row_timestamp <= end:
                                        table_or_rows_updated = True
                                        break
                            
                            if table_or_rows_updated:
                                yield self._convert_table_with_rows_to_document(table, rows)
                        
                        except ConnectorValidationError as e:
                            logger.warning(f"Failed to list rows for table {table.id}: {e}")
                            if table_timestamp > start and table_timestamp <= end:
                                yield self._convert_table_with_rows_to_document(table, [])
                
                except ConnectorValidationError as e:
                    logger.warning(f"Failed to list tables for doc {doc.id}: {e}")

        return batch_generator(_iter_documents(), self.batch_size)

    def validate_connector_settings(self) -> None:
        """Validates the Coda connector settings calling the 'whoami' endpoint."""
        if self.coda_client is None:
            raise ConnectorMissingCredentialError("Coda")
        
        try:
            response = self.coda_client.get("whoami")
            logger.info(f"Coda connector validated for user: {response.get('name', 'Unknown')}")
            
            # If workspace_id is specified, validate that it's accessible
            if self.workspace_id:
                params = {"workspaceId": self.workspace_id, "limit": "1"}
                self.coda_client.get("docs", params=params)
                logger.info(f"Validated access to workspace: {self.workspace_id}")
                
        except CodaClientRequestFailedError as e:
            if e.status_code == 401:
                raise CredentialExpiredError(
                    "Coda credential appears to be invalid or expired (HTTP 401)."
                )
            elif e.status_code == 404:
                raise ConnectorValidationError(
                    "Coda workspace not found or not accessible (HTTP 404). "
                    "Please verify the workspace_id is correct and shared with the integration."
                )
            elif e.status_code == 429:
                raise ConnectorValidationError(
                    "Validation failed due to Coda rate-limits being exceeded (HTTP 429). "
                    "Please try again later."
                )
            else:
                raise UnexpectedValidationError(
                    f"Unexpected Coda HTTP error (status={e.status_code}): {e}"
                )
        except Exception as exc:
            raise UnexpectedValidationError(
                f"Unexpected error during Coda settings validation: {exc}"
            )

