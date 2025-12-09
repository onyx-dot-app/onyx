from __future__ import annotations

from collections.abc import Generator
from time import sleep
from typing import Any

import requests

from onyx.connectors.coda.models.column import CodaColumn
from onyx.connectors.coda.models.doc import CodaDoc
from onyx.connectors.coda.models.page import CodaPage
from onyx.connectors.coda.models.table import CodaRow
from onyx.connectors.coda.models.table import CodaTableReference
from onyx.connectors.cross_connector_utils.rate_limit_wrapper import rl_requests
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.exceptions import UnexpectedValidationError
from onyx.utils.logger import setup_logger

logger = setup_logger()

_CODA_API_BASE = "https://coda.io/apis/v1"
_CODA_PAGE_SIZE = 100
_CODA_CALL_TIMEOUT = 30  # 30 seconds


class CodaAPIClient:
    """Handles all communication with the Coda API.

    Responsibilities:
    - Making authenticated requests
    - Handling pagination
    - Retrying failed requests
    - Polling async exports
    - Converting raw JSON responses to typed models
    """

    def __init__(self, api_token: str) -> None:
        """Initialize with API token."""
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_token}",
        }
        self.export_max_attempts = 10
        self.export_poll_interval = 1.0

    def validate_credentials(self) -> None:
        """Verify the API token is valid and has required permissions."""
        try:
            res = rl_requests.get(
                f"{_CODA_API_BASE}/whoami",
                headers=self.headers,
                timeout=_CODA_CALL_TIMEOUT,
            )
            res.raise_for_status()

        except requests.exceptions.HTTPError as http_err:
            status_code = http_err.response.status_code if http_err.response else None

            if status_code == 401:
                raise CredentialExpiredError(
                    "Coda credential appears to be invalid or expired (HTTP 401)."
                )
            elif status_code == 403:
                raise InsufficientPermissionsError(
                    "Your Coda token does not have sufficient permissions (HTTP 403)."
                )
            elif status_code == 429:
                raise ConnectorValidationError(
                    "Validation failed due to Coda rate-limits being exceeded (HTTP 429). "
                    "Please try again later."
                )
            else:
                raise UnexpectedValidationError(
                    f"Unexpected Coda HTTP error (status={status_code}): {http_err}"
                ) from http_err

        except Exception as exc:
            raise UnexpectedValidationError(
                f"Unexpected error validating Coda credentials: {exc}"
            )

    def _make_request(
        self, method: str, path: str, params: dict[str, Any] | None = None, **kwargs
    ) -> dict[str, Any]:
        """Make a single API request with error handling."""
        url = f"{_CODA_API_BASE}{path}"

        try:
            if method.upper() == "GET":
                res = rl_requests.get(
                    url,
                    headers=self.headers,
                    params=params,
                    timeout=_CODA_CALL_TIMEOUT,
                    **kwargs,
                )
            elif method.upper() == "POST":
                res = rl_requests.post(
                    url,
                    headers=self.headers,
                    params=params,
                    timeout=_CODA_CALL_TIMEOUT,
                    **kwargs,
                )
            elif method.upper() == "PUT":
                res = requests.put(
                    url,
                    headers=self.headers,
                    params=params,
                    timeout=_CODA_CALL_TIMEOUT,
                    **kwargs,
                )
            elif method.upper() == "DELETE":
                res = requests.delete(
                    url,
                    headers=self.headers,
                    params=params,
                    timeout=_CODA_CALL_TIMEOUT,
                    **kwargs,
                )
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            res.raise_for_status()
            return res.json()

        except Exception as e:
            try:
                error_body = res.json()
            except Exception:
                error_body = res.text if "res" in locals() else str(e)

            logger.error(f"Error making {method} request to {path}: {error_body}")
            raise

    def fetch_docs(self, page_token: str | None = None) -> dict[str, Any]:
        """Fetch paginated list of accessible docs."""
        logger.debug("Fetching Coda docs")
        params: dict[str, Any] = {"limit": _CODA_PAGE_SIZE}
        if page_token:
            params["pageToken"] = page_token

        return self._make_request("GET", "/docs", params=params)

    def fetch_all_docs(self) -> Generator[CodaDoc, None, None]:
        """Fetch all accessible docs, handling pagination automatically."""
        page_token = None
        while True:
            response = self.fetch_docs(page_token)
            docs = [CodaDoc(**doc) for doc in response.get("items", [])]

            for doc in docs:
                yield doc

            page_token = response.get("nextPageToken")
            if not page_token:
                break

    def create_doc(
        self,
        title: str | None = None,
        source_doc: str | None = None,
        timezone: str | None = None,
        folder_id: str | None = None,
        initial_page: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new Coda doc, optionally copying an existing doc.

        Note: Creating a doc requires Doc Maker permissions in the workspace.

        Args:
            title: Title of the new doc (defaults to 'Untitled')
            source_doc: Optional doc ID to copy from
            timezone: Timezone for the doc (e.g., 'America/Los_Angeles')
            folder_id: ID of folder to create doc in (defaults to 'My docs')
            initial_page: Initial page configuration dict with keys:
                - name: Page name
                - subtitle: Page subtitle
                - iconName: Icon name
                - imageUrl: Cover image URL
                - content: Markdown content

        Returns:
            dict with doc info including 'id', 'name', 'href', 'browserLink', etc.

        Raises:
            Exception: If the API request fails
        """
        logger.debug(f"Creating doc '{title or 'Untitled'}' in folder '{folder_id}'")

        body = {
            "title": title,
            "sourceDoc": source_doc,
            "timezone": timezone,
            "folderId": folder_id,
            "initialPage": initial_page,
        }

        return self._make_request("POST", "/docs", json=body)

    def fetch_pages(self, doc_id: str, page_token: str | None = None) -> dict[str, Any]:
        """Fetch paginated list of pages in a doc."""
        logger.debug(f"Fetching pages for doc '{doc_id}'")
        params: dict[str, Any] = {"limit": _CODA_PAGE_SIZE}
        if page_token:
            params["pageToken"] = page_token

        return self._make_request("GET", f"/docs/{doc_id}/pages", params=params)

    def fetch_all_pages(self, doc_id: str) -> list[CodaPage]:
        """Fetch all pages in a doc, handling pagination automatically."""
        all_pages: list[CodaPage] = []
        page_token = None

        while True:
            response = self.fetch_pages(doc_id, page_token)
            all_pages.extend([CodaPage(**page) for page in response.get("items", [])])

            page_token = response.get("nextPageToken")
            if not page_token:
                break

        return all_pages

    def create_page(
        self,
        doc_id: str,
        name: str,
        subtitle: str | None = None,
        icon_name: str | None = None,
        image_url: str | None = None,
        parent_page_id: str | None = None,
        content_html: str | None = None,
        content_markdown: str | None = None,
    ) -> dict[str, Any]:
        """Create a new page in a doc.

        Note: Creating a page requires Doc Maker permissions in the workspace.

        Args:
            doc_id: ID of the doc to create the page in
            name: Name of the new page
            subtitle: Optional subtitle for the page
            icon_name: Optional name of an icon to display
            image_url: Optional URL for a cover image
            parent_page_id: Optional ID of parent page (for creating subpages)
            content_html: Optional HTML content to add at creation
            content_markdown: Optional Markdown content to add at creation

        Returns:
            dict with 'requestId' and 'id' (the new page ID)

        Raises:
            Exception: If the API request fails
        """
        logger.debug(f"Creating page '{name}' in doc '{doc_id}'")

        # Build request body
        body: dict[str, Any] = {"name": name}

        if subtitle:
            body["subtitle"] = subtitle
        if icon_name:
            body["iconName"] = icon_name
        if image_url:
            body["imageUrl"] = image_url
        if parent_page_id:
            body["parentPageId"] = parent_page_id

        # Add content if provided
        if content_html or content_markdown:
            page_content: dict[str, Any] = {"type": "canvas"}
            canvas_content: dict[str, Any] = {}

            if content_html:
                canvas_content["format"] = "html"
                canvas_content["content"] = content_html
            elif content_markdown:
                canvas_content["format"] = "markdown"
                canvas_content["content"] = content_markdown

            page_content["canvasContent"] = canvas_content
            body["pageContent"] = page_content

        return self._make_request("POST", f"/docs/{doc_id}/pages", json=body)

    def update_page(
        self,
        doc_id: str,
        page_id: str,
        name: str | None = None,
        subtitle: str | None = None,
        icon_name: str | None = None,
        image_url: str | None = None,
        content_html: str | None = None,
        content_markdown: str | None = None,
    ) -> dict[str, Any]:
        """Update an existing page.

        Args:
            doc_id: ID of the doc
            page_id: ID of the page to update
            name: New name
            subtitle: New subtitle
            icon_name: New icon name
            image_url: New image URL
            content_html: New HTML content
            content_markdown: New Markdown content

        Returns:
            dict with 'requestId' and 'id'
        """
        logger.debug(f"Updating page '{page_id}' in doc '{doc_id}'")

        body: dict[str, Any] = {}
        if name:
            body["name"] = name
        if subtitle:
            body["subtitle"] = subtitle
        if icon_name:
            body["iconName"] = icon_name
        if image_url:
            body["imageUrl"] = image_url

        body["contentUpdate"] = {}
        if content_html:
            canvas_content: dict[str, Any] = {}
            canvas_content["format"] = "html"
            canvas_content["content"] = content_html

            body["contentUpdate"]["canvasContent"] = canvas_content
            body["contentUpdate"]["insertionMode"] = "append"

        logger.debug(f"Updating page '{page_id}' in doc '{doc_id}' with body: {body}")

        return self._make_request("PUT", f"/docs/{doc_id}/pages/{page_id}", json=body)

    def fetch_tables(
        self, doc_id: str, page_token: str | None = None
    ) -> dict[str, Any]:
        """Fetch paginated list of tables in a doc."""
        logger.debug(f"Fetching tables for doc '{doc_id}'")
        params: dict[str, Any] = {"limit": _CODA_PAGE_SIZE}
        if page_token:
            params["pageToken"] = page_token

        return self._make_request("GET", f"/docs/{doc_id}/tables", params=params)

    def fetch_all_tables(self, doc_id: str) -> list[CodaTableReference]:
        """Fetch all tables in a doc, handling pagination automatically."""
        all_tables: list[CodaTableReference] = []
        page_token = None

        while True:
            response = self.fetch_tables(doc_id, page_token)
            all_tables.extend(
                [CodaTableReference(**t) for t in response.get("items", [])]
            )

            page_token = response.get("nextPageToken")
            if not page_token:
                break

        return all_tables

    def fetch_table_columns(self, doc_id: str, table_id: str) -> list[CodaColumn]:
        """Fetch all column definitions for a table."""
        logger.debug(f"Fetching columns for table '{table_id}' in doc '{doc_id}'")
        params = {"limit": _CODA_PAGE_SIZE}

        response = self._make_request(
            "GET", f"/docs/{doc_id}/tables/{table_id}/columns", params=params
        )
        return [CodaColumn(**col) for col in response.get("items", [])]

    def fetch_table_rows(
        self,
        doc_id: str,
        table_id: str,
        page_token: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Fetch paginated rows from a table."""
        logger.debug(f"Fetching rows for table '{table_id}' in doc '{doc_id}'")
        params: dict[str, Any] = {
            "limit": limit or _CODA_PAGE_SIZE,
            "useColumnNames": False,
            "valueFormat": "rich",
        }
        if page_token:
            params["pageToken"] = page_token

        return self._make_request(
            "GET", f"/docs/{doc_id}/tables/{table_id}/rows", params=params
        )

    def fetch_all_table_rows(
        self, doc_id: str, table_id: str, max_rows: int | None = None
    ) -> list[CodaRow]:
        """Fetch all rows from a table with optional limit."""
        all_rows: list[CodaRow] = []
        page_token = None
        rows_fetched = 0

        while max_rows is None or rows_fetched < max_rows:
            remaining = (max_rows - rows_fetched) if max_rows else _CODA_PAGE_SIZE
            limit = min(remaining, _CODA_PAGE_SIZE) if max_rows else _CODA_PAGE_SIZE

            response = self.fetch_table_rows(doc_id, table_id, page_token, limit)

            batch_rows = [CodaRow(**row) for row in response.get("items", [])]

            if not batch_rows:
                break

            all_rows.extend(batch_rows)
            rows_fetched += len(batch_rows)

            page_token = response.get("nextPageToken")
            if not page_token:
                break

        return all_rows

    def upsert_rows(
        self,
        doc_id: str,
        table_id: str,
        rows: list[dict[str, Any]],
        key_columns: list[str] | None = None,
    ) -> dict[str, Any]:
        """Insert or update rows in a table.

        Args:
            doc_id: ID of the doc
            table_id: ID of the table
            rows: List of rows to upsert. Each row is a dict of {column_id: value}
                  or a dict with 'cells' key matching Coda API format.
            key_columns: Optional list of column IDs to use as keys for upserting

        Returns:
            dict with 'requestId'
        """
        logger.debug(
            f"Upserting {len(rows)} rows to table '{table_id}' in doc '{doc_id}'"
        )

        formatted_rows = []
        for row in rows:
            # If row is already in Coda format (has 'cells'), use it
            if "cells" in row:
                formatted_rows.append(row)
                continue

            # Otherwise convert simple dict {col: val} to Coda format
            cells = []
            for col, val in row.items():
                cells.append({"column": col, "value": val})
            formatted_rows.append({"cells": cells})

        body = {"rows": formatted_rows}
        if key_columns:
            body["keyColumns"] = key_columns

        return self._make_request(
            "POST", f"/docs/{doc_id}/tables/{table_id}/rows", json=body
        )

    def export_page_content(
        self, doc_id: str, page_id: str, output_format: str = "markdown"
    ) -> str | None:
        """Export page content via async API.

        Args:
            doc_id: ID of the doc containing the page
            page_id: ID of the page to export
            output_format: Export format - 'markdown' or 'html' (default: 'markdown')

        Returns:
            str: Page content in the specified format
            None: If export failed (API error, timeout, etc.)
        """
        logger.debug(
            f"Exporting content for page '{page_id}' in doc '{doc_id}' as {output_format}"
        )

        # Start the export
        try:
            response = self._make_request(
                "POST",
                f"/docs/{doc_id}/pages/{page_id}/export",
                json={"outputFormat": output_format},
            )
        except Exception as e:
            logger.warning(f"Error starting export for page '{page_id}': {e}")
            return None

        request_id = response.get("id")

        if not request_id:
            logger.warning(f"No request ID returned for page '{page_id}'")
            return None

        # Wait a moment for the export request to be registered
        sleep(2)

        # Poll for the export result with exponential backoff
        for attempt in range(self.export_max_attempts):
            # Exponential backoff: 1s, 2s, 4s, 8s, etc.
            wait_time = self.export_poll_interval * (2**attempt)

            try:
                status_response = self._make_request(
                    "GET",
                    f"/docs/{doc_id}/pages/{page_id}/export/{request_id}",
                )
            except Exception as e:
                logger.warning(
                    f"Error checking export status for page '{page_id}' (attempt {attempt + 1}/{self.export_max_attempts}): {e}"
                )
                # Always retry until max attempts reached
                if attempt < self.export_max_attempts - 1:
                    sleep(wait_time)
                continue

            logger.warning(
                f"Export status for page '{page_id}' (attempt {attempt + 1}/{self.export_max_attempts}): {status_response}"
            )
            status = status_response.get("status")

            if status == "complete":
                download_link = status_response.get("downloadLink")
                if not download_link:
                    logger.warning(f"No download link for page '{page_id}'")
                    return None

                try:
                    content_res = rl_requests.get(
                        download_link, timeout=_CODA_CALL_TIMEOUT, allow_redirects=True
                    )
                    content_res.raise_for_status()
                    content = content_res.text

                    # Validate content is not empty
                    if not content.strip():
                        logger.warning(
                            f"Page '{page_id}' exported but contains no content"
                        )
                        return None

                    logger.debug(
                        f"Successfully exported page '{page_id}' ({len(content)} chars)"
                    )
                    return content
                except Exception as e:
                    logger.warning(
                        f"Error downloading content for page '{page_id}': {e}"
                    )
                    return None

            elif status == "failed":
                logger.warning(f"Export failed for page '{page_id}'")
                return None

            elif status == "inProgress":
                # Only log on first attempt to avoid spam
                if attempt == 0:
                    logger.debug(f"Export in progress for page '{page_id}'")

                # Wait before polling again (exponential backoff)
                if attempt < self.export_max_attempts - 1:
                    sleep(wait_time)

            else:
                logger.warning(f"Unknown export status '{status}' for page '{page_id}'")
                return None

        logger.warning(
            f"Export timed out for page '{page_id}' after {self.export_max_attempts} attempts"
        )
        return None
