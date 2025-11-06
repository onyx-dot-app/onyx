from __future__ import annotations

from datetime import datetime, timezone
import re
import html as html_lib
from typing import Any, ClassVar, Iterator, Optional

import requests

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
from onyx.utils.logger import setup_logger


logger = setup_logger()

# Size management to avoid oversized docs filling the index
MAX_DOC_CHARS = 20000  # truncate content above this size
SKIP_DOC_ABSOLUTE_CHARS = 200000  # skip documents entirely above this size


class TestRailConnector(LoadConnector, PollConnector):
    """Connector for TestRail.

    Minimal implementation that indexes Test Cases per project.
    """

    document_source_type: ClassVar[DocumentSource] = DocumentSource.TESTRAIL

    def __init__(
        self,
        base_url: str | None = None,
        username: str | None = None,
        api_key: str | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        project_ids: list[int] | None = None,
    ) -> None:
        self.base_url = base_url
        self.username = username
        self.api_key = api_key
        self.batch_size = batch_size
        self.project_ids = project_ids

    # --- Rich text sanitization helpers ---
    @staticmethod
    def _sanitize_rich_text(value: Any) -> str:
        if value is None:
            return ""
        text = str(value)
        # Replace common HTML breaks with newlines (case-insensitive)
        text = re.sub(r"(?i)<br\s*/?>", "\n", text)
        text = re.sub(r"(?i)</p>", "\n", text)
        text = re.sub(r"(?i)</div>", "\n", text)
        # Remove <img ...> entirely (avoid base64/data URIs)
        text = re.sub(r"(?is)<img[^>]*>", "", text)
        # Remove explicit data:image URIs if present anywhere
        text = re.sub(r"data:image/[^\"' )]+;base64,[A-Za-z0-9+/=]+", "[image removed]", text)
        # Strip remaining HTML tags
        text = re.sub(r"<[^>]+>", "", text)
        # Unescape HTML entities
        text = html_lib.unescape(text)
        # Normalize whitespace
        return re.sub(r"\s+", " ", text).strip()

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        # Expected keys from UI credential JSON
        self.base_url = str(credentials["testrail_base_url"]).rstrip("/")
        self.username = str(credentials["testrail_username"])  # email or username
        self.api_key = str(credentials["testrail_api_key"])  # API key (password)
        return None

    def validate_connector_settings(self) -> None:
        """Lightweight validation to surface common misconfigurations early."""
        try:
            projects = self._list_projects()
        except Exception as e:
            raise ConnectorMissingCredentialError(
                f"TestRail credentials or base URL invalid: {e}"
            )
        if not projects:
            logger.warning("TestRail: no projects visible to this credential.")

    # ---- HTTP helpers ----
    def _api_get(self, endpoint: str, params: Optional[dict[str, Any]] = None) -> Any:
        if not self.base_url or not self.username or not self.api_key:
            raise ConnectorMissingCredentialError("testrail")

        # TestRail API base is typically /index.php?/api/v2/<endpoint>
        url = f"{self.base_url}/index.php?/api/v2/{endpoint}"
        response = requests.get(url, auth=(self.username, self.api_key), params=params)
        response.raise_for_status()
        return response.json()

    def _list_projects(self) -> list[dict[str, Any]]:
        projects = self._api_get("get_projects")
        if isinstance(projects, list):
            return projects
        if isinstance(projects, dict):
            # Handle wrapped responses like {"projects": [...]} or {"items": [...]} or {"data": [...]}
            for key in ("projects", "items", "data", "results"):
                val = projects.get(key)
                if isinstance(val, list):
                    return val
        logger.warning("Unexpected TestRail projects response shape")
        return []

    def _list_suites(self, project_id: int) -> list[dict[str, Any]]:
        """Return suites for a project. If the project is in single-suite mode,
        some TestRail instances may return an empty list; callers should
        gracefully fallback to calling get_cases without suite_id.
        """
        suites = self._api_get(f"get_suites/{project_id}")
        if isinstance(suites, list):
            return suites
        if isinstance(suites, dict):
            for key in ("suites", "items", "data", "results"):
                val = suites.get(key)
                if isinstance(val, list):
                    return val
        logger.warning("Unexpected TestRail suites response shape")
        return []

    def _iter_cases(
        self,
        project_id: int,
        suite_id: Optional[int] = None,
        start: Optional[SecondsSinceUnixEpoch] = None,
        end: Optional[SecondsSinceUnixEpoch] = None,
    ) -> Iterator[dict[str, Any]]:
        # Pagination: TestRail supports 'limit' and 'offset' for many list endpoints
        limit = 250
        offset = 0
        while True:
            params: dict[str, Any] = {"limit": limit, "offset": offset}
            if suite_id is not None:
                params["suite_id"] = suite_id
            cases = self._api_get(f"get_cases/{project_id}", params=params)
            if isinstance(cases, dict):
                for key in ("cases", "items", "data", "results"):
                    val = cases.get(key)
                    if isinstance(val, list):
                        cases = val
                        break

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
            offset += limit

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
        if case.get("type_id") is not None:
            text_lines.append(f"Type ID: {case['type_id']}")
        if case.get("priority_id") is not None:
            text_lines.append(f"Priority ID: {case['priority_id']}")
        if case.get("estimate"):
            text_lines.append(f"Estimate: {case['estimate']}")
        if case.get("refs"):
            text_lines.append(f"Refs: {case['refs']}")
        pre = self._sanitize_rich_text(case.get("custom_preconds"))
        if pre:
            text_lines.append(f"Preconditions: {pre}")
        steps = self._sanitize_rich_text(case.get("custom_steps"))
        if steps:
            text_lines.append(f"Steps: {steps}")
        exp = self._sanitize_rich_text(case.get("custom_expected"))
        if exp:
            text_lines.append(f"Expected: {exp}")

        link = self._build_case_link(project_id, case_id)

        # Build full text and apply size policies
        full_text = "\n".join(text_lines)
        if len(full_text) > SKIP_DOC_ABSOLUTE_CHARS:
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

        # Apply truncation if needed
        if len(full_text) > MAX_DOC_CHARS:
            doc_metadata["truncated"] = "true"
            full_text = full_text[:MAX_DOC_CHARS] + "\n[Truncated due to size]"

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
            pid = project.get("id")
            if project_filter and pid not in project_filter:
                continue

            suites = self._list_suites(pid)
            if suites:
                for s in suites:
                    sid = s.get("id")
                    for case in self._iter_cases(pid, sid, start, end):
                        doc = self._doc_from_case(project, case, s)
                        if doc is None:
                            continue
                        doc_batch.append(doc)
                        if len(doc_batch) >= self.batch_size:
                            yield doc_batch
                            doc_batch = []
            else:
                # single-suite mode fallback
                for case in self._iter_cases(pid, None, start, end):
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
    # Simple local test harness similar to other connectors.
    # Env vars (examples):
    #   TESTRAIL_BASE_URL=https://yourcompany.testrail.io
    #   TESTRAIL_USERNAME=you@example.com
    #   TESTRAIL_API_KEY=your_api_key_or_password
    #   TESTRAIL_PROJECT_ID=123            (optional)
    #   TESTRAIL_SUITE_ID=456              (optional)
    import os

    base = os.environ.get("TESTRAIL_BASE_URL", "").strip()
    user = os.environ.get("TESTRAIL_USERNAME", "").strip()
    key = os.environ.get("TESTRAIL_API_KEY", "").strip()
    project_id = os.environ.get("TESTRAIL_PROJECT_ID")
    suite_id = os.environ.get("TESTRAIL_SUITE_ID")

    cred = {
        "testrail_base_url": base,
        "testrail_username": user,
        "testrail_api_key": key,
    }
    connector = TestRailConnector(
        project_ids=[int(project_id)] if project_id else None,
    )
    connector.load_credentials(cred)
    connector.validate_connector_settings()

    # Probe a tiny batch from load
    total = 0
    for batch in connector.load_from_state():
        print(f"Fetched batch: {len(batch)} docs")
        total += len(batch)
        if total >= 10:
            break
    print(f"Total fetched in test: {total}")

