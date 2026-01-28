from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import ClassVar
from typing import Optional

import requests
from bs4 import BeautifulSoup

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.exceptions import UnexpectedValidationError
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import HierarchyNode
from onyx.connectors.models import TextSection
from onyx.file_processing.html_utils import format_document_soup
from onyx.utils.logger import setup_logger
from onyx.utils.text_processing import remove_markdown_image_references


logger = setup_logger()


class TestRailConnector(LoadConnector, PollConnector):
    """Connector for TestRail.

    Minimal implementation that indexes Test Cases per project.
    """

    document_source_type: ClassVar[DocumentSource] = DocumentSource.TESTRAIL

    # Fields that need ID-to-label value mapping
    FIELDS_NEEDING_VALUE_MAPPING: ClassVar[set[str]] = {
        "priority_id",
        "custom_automation_type",
        "custom_scenario_db_automation",
        "custom_case_golden_canvas_automation",
        "custom_customers",
        "custom_case_environments",
        "custom_case_overall_automation",
        "custom_case_team_ownership",
        "custom_case_unit_or_integration_automation",
        "custom_effort",
    }

    def __init__(
        self,
        batch_size: int = INDEX_BATCH_SIZE,
        project_ids: str | list[int] | None = None,
        cases_page_size: int | None = None,
        max_pages: int | None = None,
        skip_doc_absolute_chars: int | None = None,
    ) -> None:
        self.base_url: str | None = None
        self.username: str | None = None
        self.api_key: str | None = None
        self.batch_size = batch_size
        parsed_project_ids: list[int] | None

        # Parse project_ids from string if needed
        # None = all projects (no filtering), [] = no projects, [1,2,3] = specific projects
        if isinstance(project_ids, str):
            if project_ids.strip():
                parsed_project_ids = [
                    int(x.strip()) for x in project_ids.split(",") if x.strip()
                ]
            else:
                # Empty string from UI means "all projects"
                parsed_project_ids = None
        elif project_ids is None:
            parsed_project_ids = None
        else:
            parsed_project_ids = [int(pid) for pid in project_ids]

        self.project_ids: list[int] | None = parsed_project_ids

        # Handle empty strings from UI and convert to int with defaults
        self.cases_page_size = (
            int(cases_page_size)
            if cases_page_size and str(cases_page_size).strip()
            else 250
        )
        self.max_pages = (
            int(max_pages) if max_pages and str(max_pages).strip() else 10000
        )
        self.skip_doc_absolute_chars = (
            int(skip_doc_absolute_chars)
            if skip_doc_absolute_chars and str(skip_doc_absolute_chars).strip()
            else 200000
        )

        # Cache for field labels and value mappings - will be populated on first use
        self._field_labels: dict[str, str] | None = None
        self._value_maps: dict[str, dict[str, str]] | None = None

    # --- Rich text sanitization helpers ---
    # Note: TestRail stores some fields as HTML (e.g. shared test steps).
    # This function handles both HTML and plain text.
    @staticmethod
    def _sanitize_rich_text(value: Any) -> str:
        if value is None:
            return ""
        text = str(value)

        # Parse HTML and remove image tags
        soup = BeautifulSoup(text, "html.parser")

        # Remove all img tags and their containers
        for img_tag in soup.find_all("img"):
            img_tag.decompose()
        for span in soup.find_all("span", class_="markdown-img-container"):
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
            raise UnexpectedValidationError(
                "Invalid JSON returned by TestRail API"
            ) from e

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

    def _get_case_fields(self) -> list[dict[str, Any]]:
        """Get case field definitions from TestRail API."""
        try:
            fields = self._api_get("get_case_fields")
            return fields if isinstance(fields, list) else []
        except Exception as e:
            logger.warning(f"Failed to fetch case fields from TestRail: {e}")
            return []

    def _parse_items_string(self, items_str: str) -> dict[str, str]:
        """Parse items string from field config into ID -> label mapping.

        Format: "1, Option A\\n2, Option B\\n3, Option C"
        Returns: {"1": "Option A", "2": "Option B", "3": "Option C"}
        """
        id_to_label: dict[str, str] = {}
        if not items_str:
            return id_to_label

        for line in items_str.split("\n"):
            line = line.strip()
            if not line:
                continue
            parts = line.split(",", 1)
            if len(parts) == 2:
                item_id = parts[0].strip()
                item_label = parts[1].strip()
                id_to_label[item_id] = item_label

        return id_to_label

    def _build_field_maps(self) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
        """Build both field labels and value mappings in one pass.

        Returns:
            (field_labels, value_maps) where:
            - field_labels: system_name -> label
            - value_maps: system_name -> {id -> label}
        """
        field_labels = {}
        value_maps = {}

        try:
            fields = self._get_case_fields()
            for field in fields:
                system_name = field.get("system_name")

                # Build field label map
                label = field.get("label")
                if system_name and label:
                    field_labels[system_name] = label

                # Build value map if needed
                if system_name in self.FIELDS_NEEDING_VALUE_MAPPING:
                    configs = field.get("configs", [])
                    if configs and len(configs) > 0:
                        options = configs[0].get("options", {})
                        items_str = options.get("items")
                        if items_str:
                            value_maps[system_name] = self._parse_items_string(
                                items_str
                            )

        except Exception as e:
            logger.warning(f"Failed to build field maps from TestRail: {e}")

        return field_labels, value_maps

    def _get_field_labels(self) -> dict[str, str]:
        """Get field labels, fetching from API if not cached."""
        if self._field_labels is None:
            self._field_labels, self._value_maps = self._build_field_maps()
        return self._field_labels

    def _get_value_maps(self) -> dict[str, dict[str, str]]:
        """Get value maps, fetching from API if not cached."""
        if self._value_maps is None:
            self._field_labels, self._value_maps = self._build_field_maps()
        return self._value_maps

    def _map_field_value(self, field_name: str, field_value: Any) -> str:
        """Map a field value using the value map if available.

        Examples:
        - priority_id: 2 -> "Medium"
        - custom_case_team_ownership: [10] -> "Sim Platform"
        - custom_case_environments: [1, 2] -> "Local, Cloud"
        """
        if field_value is None or field_value == "":
            return ""

        # Get value map for this field
        value_maps = self._get_value_maps()
        value_map = value_maps.get(field_name, {})

        # Handle list values
        if isinstance(field_value, list):
            if not field_value:
                return ""
            mapped = [value_map.get(str(v), str(v)) for v in field_value]
            return ", ".join(mapped)

        # Handle single values
        val_str = str(field_value)
        return value_map.get(val_str, val_str)

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
        if not isinstance(project_id, int):
            logger.warning(
                "Skipping TestRail case because project id is missing or invalid: %s",
                project_id,
            )
            return None

        case_id = case.get("id")
        if not isinstance(case_id, int):
            logger.warning(
                "Skipping TestRail case because case id is missing or invalid: %s",
                case_id,
            )
            return None

        title = case.get("title", f"Case {case_id}")
        case_key = f"C{case_id}"

        # Convert epoch seconds to aware datetime if available
        updated = case.get("updated_on") or case.get("created_on")
        updated_dt = (
            datetime.fromtimestamp(updated, tz=timezone.utc)
            if isinstance(updated, (int, float))
            else None
        )

        text_lines: list[str] = []
        if case.get("title"):
            text_lines.append(f"Title: {case['title']}")
        if case_key:
            text_lines.append(f"Case ID: {case_key}")
        if case_id is not None:
            text_lines.append(f"ID: {case_id}")
        doc_link = case.get("custom_documentation_link")
        if doc_link:
            text_lines.append(f"Documentation: {doc_link}")

        # Add fields that need value mapping
        field_labels = self._get_field_labels()
        for field_name in self.FIELDS_NEEDING_VALUE_MAPPING:
            field_value = case.get(field_name)
            if field_value is not None and field_value != "" and field_value != []:
                mapped_value = self._map_field_value(field_name, field_value)
                if mapped_value:
                    # Get label from TestRail field definition
                    label = field_labels.get(
                        field_name, field_name.replace("_", " ").title()
                    )
                    text_lines.append(f"{label}: {mapped_value}")

        pre = self._sanitize_rich_text(case.get("custom_preconds"))
        if pre:
            text_lines.append(f"Preconditions: {pre}")

        # Steps: use separated steps format if available
        steps_added = False
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
                steps_added = True

        # Fallback to custom_steps and custom_expected if no separated steps
        if not steps_added:
            custom_steps = self._sanitize_rich_text(case.get("custom_steps"))
            custom_expected = self._sanitize_rich_text(case.get("custom_expected"))
            if custom_steps:
                text_lines.append(f"Steps: {custom_steps}")
            if custom_expected:
                text_lines.append(f"Expected: {custom_expected}")

        link = self._build_case_link(project_id, case_id)

        # Build full text and apply size policies
        full_text = "\n".join(text_lines)
        if len(full_text) > self.skip_doc_absolute_chars:
            logger.warning(
                f"Skipping TestRail case {case_id} due to excessive size: {len(full_text)} chars"
            )
            return None

        # Metadata for document identification
        metadata: dict[str, Any] = {}
        if case_key:
            metadata["case_key"] = case_key

        # Include the human-friendly case key in identifiers for easier search
        display_title = f"{case_key}: {title}" if case_key else title

        return Document(
            id=f"TESTRAIL_CASE_{case_id}",
            source=DocumentSource.TESTRAIL,
            semantic_identifier=display_title,
            title=display_title,
            sections=[TextSection(link=link, text=full_text)],
            metadata=metadata,
            doc_updated_at=updated_dt,
        )

    def _generate_documents(
        self,
        start: Optional[SecondsSinceUnixEpoch],
        end: Optional[SecondsSinceUnixEpoch],
    ) -> GenerateDocumentsOutput:
        if not self.base_url or not self.username or not self.api_key:
            raise ConnectorMissingCredentialError("testrail")

        doc_batch: list[Document | HierarchyNode] = []

        projects = self._list_projects()
        project_filter: list[int] | None = self.project_ids

        for project in projects:
            project_id_raw = project.get("id")
            if not isinstance(project_id_raw, int):
                logger.warning(
                    "Skipping TestRail project with invalid id: %s", project_id_raw
                )
                continue
            project_id = project_id_raw
            # None = index all, [] = index none, [1,2,3] = index only those
            if project_filter is not None and project_id not in project_filter:
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
