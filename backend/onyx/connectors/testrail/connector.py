from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, ClassVar, Iterator, Optional

import requests
from bs4 import BeautifulSoup

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
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
from onyx.connectors.exceptions import (
    CredentialExpiredError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.utils.logger import setup_logger
from onyx.utils.text_processing import remove_markdown_image_references
from onyx.file_processing.html_utils import format_document_soup


logger = setup_logger()



class TestRailConnector(LoadConnector, PollConnector):
    """Connector for TestRail.

    Minimal implementation that indexes Test Cases per project.
    """

    document_source_type: ClassVar[DocumentSource] = DocumentSource.TESTRAIL

    def __init__(
        self,
        batch_size: int = INDEX_BATCH_SIZE,
        project_ids: list[int] | None = None,
        cases_page_size: int | None = None,
        max_pages: int | None = None,
        skip_doc_absolute_chars: int | None = None,
    ) -> None:
        self.base_url: str | None = None
        self.username: str | None = None
        self.api_key: str | None = None
        self.batch_size = batch_size
        self.project_ids = project_ids
        # Use provided values or fall back to defaults
        self.cases_page_size = cases_page_size if cases_page_size is not None else 250
        self.max_pages = max_pages if max_pages is not None else 10000
        self.skip_doc_absolute_chars = (
            skip_doc_absolute_chars if skip_doc_absolute_chars is not None else 200000
        )

    # --- Rich text sanitization helpers ---
    # Note: TestRail stores some fields as HTML (e.g. shared test steps).
    # This function handles both HTML and plain text.
    @staticmethod
    def _sanitize_rich_text(value: Any) -> str:
        if value is None:
            return ""
        text = str(value)

        # Parse HTML and remove image tags
        soup = BeautifulSoup(text, 'html.parser')

        # Remove all img tags and their containers
        for img_tag in soup.find_all('img'):
            img_tag.decompose()
        for span in soup.find_all('span', class_='markdown-img-container'):
            span.decompose()

        # Use format_document_soup for better HTML-to-text conversion
        # This preserves document structure (paragraphs, lists, line breaks, etc.)
        text = format_document_soup(soup)

        # Also remove markdown-style image references (in case any remain)
        text = remove_markdown_image_references(text)

        return text.strip()

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        # Expected keys from UI credential JSON
        self.base_url = str(credentials["testrail_base_url"]).rstrip("/")
        self.username = str(credentials["testrail_username"])  # email or username
        self.api_key = str(credentials["testrail_api_key"])  # API key (password)
        return None

    def validate_connector_settings(self) -> None:
        """Lightweight validation to surface common misconfigurations early."""
        projects = self._list_projects()
        if not projects:
            logger.warning("TestRail: no projects visible to this credential.")

    # ---- API helpers ----
    def _api_get(self, endpoint: str, params: Optional[dict[str, Any]] = None) -> Any:
        if not self.base_url or not self.username or not self.api_key:
            raise ConnectorMissingCredentialError("testrail")

        # TestRail API base is typically /index.php?/api/v2/<endpoint>
        url = f"{self.base_url}/index.php?/api/v2/{endpoint}"
        try:
            response = requests.get(
                url,
                auth=(self.username, self.api_key),
                params=params,
            )
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if getattr(e, "response", None) else None
            if status == 401:
                raise CredentialExpiredError(
                    "Invalid or expired TestRail credentials (HTTP 401)."
                ) from e
            if status == 403:
                raise InsufficientPermissionsError(
                    "Insufficient permissions to access TestRail resources (HTTP 403)."
                ) from e
            raise UnexpectedValidationError(
                f"Unexpected TestRail HTTP error (status={status})."
            ) from e
        except requests.exceptions.RequestException as e:
            raise UnexpectedValidationError(f"TestRail request failed: {e}") from e

        try:
            return response.json()
        except ValueError as e:
            raise UnexpectedValidationError("Invalid JSON returned by TestRail API") from e

    def _list_projects(self) -> list[dict[str, Any]]:
        projects = self._api_get("get_projects")
        if isinstance(projects, dict):
            projects_list = projects.get("projects")
            return projects_list if isinstance(projects_list, list) else []
        return []

    def _list_suites(self, project_id: int) -> list[dict[str, Any]]:
        """Return suites for a project. If the project is in single-suite mode,
        some TestRail instances may return an empty list; callers should
        gracefully fallback to calling get_cases without suite_id.
        """
        suites = self._api_get(f"get_suites/{project_id}")
        if isinstance(suites, dict):
            suites_list = suites.get("suites")
            return suites_list if isinstance(suites_list, list) else []
        return []

    def _get_cases(
        self, project_id: int, suite_id: Optional[int], limit: int, offset: int
    ) -> list[dict[str, Any]]:
        """Get cases for a project from the API."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if suite_id is not None:
            params["suite_id"] = suite_id
        cases_response = self._api_get(f"get_cases/{project_id}", params=params)
        cases_list: list[dict[str, Any]] = []
        if isinstance(cases_response, dict):
            cases_items = cases_response.get("cases")
            if isinstance(cases_items, list):
                cases_list = cases_items
        return cases_list

    def _iter_cases(
        self,
        project_id: int,
        suite_id: Optional[int] = None,
        start: Optional[SecondsSinceUnixEpoch] = None,
        end: Optional[SecondsSinceUnixEpoch] = None,
    ) -> Iterator[dict[str, Any]]:
        # Pagination: TestRail supports 'limit' and 'offset' for many list endpoints
        limit = self.cases_page_size
        # Use a bounded page loop to avoid infinite loops on API anomalies
        for page_index in range(self.max_pages):
            offset = page_index * limit
            cases = self._get_cases(project_id, suite_id, limit, offset)

            if not cases:
                break

            # Filter by updated window if provided
            for case in cases:
                # 'updated_on' is unix timestamp (seconds)
                updated_on = case.get("updated_on") or case.get("created_on")
                if start is not None and updated_on is not None and updated_on < start:
                    continue
                if end is not None and updated_on is not None and updated_on > end:
                    continue
                yield case

            if len(cases) < limit:
                break

    def _build_case_link(self, project_id: int, case_id: int) -> str:
        # Standard UI link to a case
        return f"{self.base_url}/index.php?/cases/view/{case_id}"

    def _doc_from_case(
        self,
        project: dict[str, Any],
        case: dict[str, Any],
        suite: dict[str, Any] | None = None,
    ) -> Document | None:
        project_id = project.get("id")
        project_name = project.get("name", f"Project {project_id}")
        case_id = case.get("id")
        title = case.get("title", f"Case {case_id}")
        case_key = f"C{case_id}" if case_id is not None else None
        suite_id = suite.get("id") if suite else None
        suite_name = suite.get("name") if suite else None
        section_name = case.get("section_id")

        # Convert epoch seconds to aware datetime if available
        updated = case.get("updated_on") or case.get("created_on")
        updated_dt = (
            datetime.fromtimestamp(updated, tz=timezone.utc) if isinstance(updated, (int, float)) else None
        )

        text_lines: list[str] = []
        if case.get("title"):
            text_lines.append(f"Title: {case['title']}")
        if case_key:
            text_lines.append(f"Case ID: {case_key}")
        if case_id is not None:
            text_lines.append(f"ID: {case_id}")
        if case.get("refs"):
            text_lines.append(f"Refs: {case['refs']}")
        doc_link = case.get("custom_documentation_link")
        if doc_link:
            text_lines.append(f"Documentation: {doc_link}")
        pre = self._sanitize_rich_text(case.get("custom_preconds"))
        if pre:
            text_lines.append(f"Preconditions: {pre}")
        # Steps: only use separated steps format
        steps_separated = case.get("custom_steps_separated")
        if isinstance(steps_separated, list) and steps_separated:
            rendered_steps: list[str] = []
            for idx, step_item in enumerate(steps_separated, start=1):
                step_content = self._sanitize_rich_text(step_item.get("content"))
                step_expected = self._sanitize_rich_text(step_item.get("expected"))
                parts: list[str] = []
                if step_content:
                    parts.append(f"Step {idx}: {step_content}")
                else:
                    parts.append(f"Step {idx}:")
                if step_expected:
                    parts.append(f"Expected: {step_expected}")
                rendered_steps.append("\n".join(parts))
            if rendered_steps:
                text_lines.append("Steps:\n" + "\n".join(rendered_steps))

        link = self._build_case_link(project_id, case_id)

        # Build full text and apply size policies
        full_text = "\n".join(text_lines)
        if len(full_text) > self.skip_doc_absolute_chars:
            logger.warning(
                f"Skipping TestRail case {case_id} due to excessive size: {len(full_text)} chars"
            )
            return None

        # Keep tags minimal and high-cardinality to avoid duplicate Tag insertions
        # Store structural identifiers in doc_metadata instead
        metadata: dict[str, Any] = {}
        if case_key:
            metadata["case_key"] = case_key

        # Non-tag metadata stored here to avoid tag uniqueness conflicts
        doc_metadata: dict[str, Any] = {}
        if project_id is not None:
            doc_metadata["project_id"] = str(project_id)
        if project_name is not None:
            doc_metadata["project_name"] = str(project_name)
        if section_name is not None:
            doc_metadata["section_id"] = str(section_name)
        if case_id is not None:
            doc_metadata["numeric_id"] = str(case_id)
        if suite_id is not None:
            doc_metadata["suite_id"] = str(suite_id)
        if suite_name is not None:
            doc_metadata["suite_name"] = str(suite_name)

        # Include the human-friendly case key in identifiers for easier search
        display_title = f"{case_key}: {title}" if case_key else title

        return Document(
            id=f"TESTRAIL_CASE_{case_id}",
            source=DocumentSource.TESTRAIL,
            semantic_identifier=display_title,
            title=display_title,
            sections=[TextSection(link=link, text=full_text)],
            metadata=metadata,
            doc_metadata=doc_metadata,
            doc_updated_at=updated_dt,
        )

    def _generate_documents(
        self,
        start: Optional[SecondsSinceUnixEpoch],
        end: Optional[SecondsSinceUnixEpoch],
    ) -> GenerateDocumentsOutput:
        if not self.base_url or not self.username or not self.api_key:
            raise ConnectorMissingCredentialError("testrail")

        doc_batch: list[Document] = []

        projects = self._list_projects()
        project_filter: list[int] | None = self.project_ids

        for project in projects:
            project_id = project.get("id")
            if project_filter and project_id not in project_filter:
                continue

            suites = self._list_suites(project_id)
            if suites:
                for s in suites:
                    suite_id = s.get("id")
                    for case in self._iter_cases(project_id, suite_id, start, end):
                        doc = self._doc_from_case(project, case, s)
                        if doc is None:
                            continue
                        doc_batch.append(doc)
                        if len(doc_batch) >= self.batch_size:
                            yield doc_batch
                            doc_batch = []
            else:
                # single-suite mode fallback
                for case in self._iter_cases(project_id, None, start, end):
                    doc = self._doc_from_case(project, case, None)
                    if doc is None:
                        continue
                    doc_batch.append(doc)
                    if len(doc_batch) >= self.batch_size:
                        yield doc_batch
                        doc_batch = []

        if doc_batch:
            yield doc_batch

    # ---- Onyx interfaces ----
    def load_from_state(self) -> GenerateDocumentsOutput:
        return self._generate_documents(start=None, end=None)

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        return self._generate_documents(start=start, end=end)



if __name__ == "__main__":
    from onyx.configs.app_configs import (
        TESTRAIL_API_KEY,
        TESTRAIL_BASE_URL,
        TESTRAIL_USERNAME,
    )

    connector = TestRailConnector()

    connector.load_credentials(
        {
            "testrail_base_url": TESTRAIL_BASE_URL,
            "testrail_username": TESTRAIL_USERNAME,
            "testrail_api_key": TESTRAIL_API_KEY,
        }
    )

    connector.validate_connector_settings()

    # Probe a tiny batch from load
    total = 0
    for batch in connector.load_from_state():
        print(f"Fetched batch: {len(batch)} docs")
        total += len(batch)
        if total >= 10:
            break
    print(f"Total fetched in test: {total}")

