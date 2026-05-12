"""
Jira Service Management (JSM) Connector.

Subclasses JiraConnector, overriding only what is strictly JSM-specific:
  - _get_document_source(): returns JIRA_SERVICE_MANAGEMENT
  - _enrich_document(): attaches SLA and JSM-specific metadata
  - __init__(): adds SLA discovery state variables

All indexing, pagination, checkpoint, hierarchy, and permission logic
is inherited from JiraConnector without duplication.  Permission
prefixing uses the _get_document_source() hook in the base class, so
no _get_project_permissions override is needed.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar, Final

from jira.resources import Issue
from typing_extensions import override

from onyx.configs.app_configs import INDEX_BATCH_SIZE, JIRA_CONNECTOR_LABELS_TO_SKIP
from onyx.configs.constants import DocumentSource
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.models import Document
from onyx.utils.logger import setup_logger

logger = setup_logger()

# ---------------------------------------------------------------------------
# SLA field-name patterns
# ---------------------------------------------------------------------------
_SLA_FIELD_PATTERNS: Final[list[tuple[str, str]]] = [
    (r"time\s+to\s+first\s+response", "sla_time_to_first_response"),
    (r"time\s+to\s+resolution", "sla_time_to_resolution"),
    (r"time\s+to\s+close", "sla_time_to_close"),
    (r"time\s+to\s+respond", "sla_time_to_respond"),
    (r"time\s+to\s+approve", "sla_time_to_approve"),
    (r"satisfaction\s+rating", "jsm_satisfaction_rating"),
]

_COMPILED_SLA_PATTERNS: Final[list[tuple[re.Pattern[str], str]]] = [
    (re.compile(pat, re.IGNORECASE), key) for pat, key in _SLA_FIELD_PATTERNS
]

_CUSTOMER_REQUEST_TYPE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"customer\s+request\s+type", re.IGNORECASE
)

_META_REQUEST_TYPE: Final[str] = "jsm_request_type"
_META_SERVICE_DESK: Final[str] = "jsm_service_desk_id"
_BREACH_SUFFIX: Final[str] = "_breached"


# ---------------------------------------------------------------------------
# SLA value extraction helpers (module-level — tested directly in unit tests)
# ---------------------------------------------------------------------------


def _extract_sla_display(sla_field_value: Any) -> tuple[str | None, bool]:
    """Return (human-readable SLA string | None, is_breached).

    Handles both JSM deployment formats:
    - Cloud: nested dict with ongoingCycle / completedCycles
    - Server / Data Center: plain string or simple dict
    """
    if sla_field_value is None:
        return None, False

    if isinstance(sla_field_value, str):
        return sla_field_value or None, False

    if not isinstance(sla_field_value, dict):
        return None, False

    if "text" in sla_field_value and "ongoingCycle" not in sla_field_value:
        text = sla_field_value.get("text") or None
        breached = bool(sla_field_value.get("breached", False))
        return text, breached

    ongoing = sla_field_value.get("ongoingCycle")
    if isinstance(ongoing, dict):
        remaining = ongoing.get("remainingTime", {})
        friendly = remaining.get("friendly") if isinstance(remaining, dict) else None
        breached = bool(ongoing.get("breached", False))
        if not friendly:
            friendly = "Breached" if breached else None
        return friendly, breached

    completed = sla_field_value.get("completedCycles")
    if isinstance(completed, list) and completed:
        last = completed[-1]
        if isinstance(last, dict):
            remaining = last.get("remainingTime", {})
            friendly = (
                remaining.get("friendly") if isinstance(remaining, dict) else None
            )
            breached = bool(last.get("breached", False))
            return friendly, breached

    return None, False


def _get_raw_field(issue: Issue, field_id: str) -> Any:
    """Safely retrieve a raw field value from an Issue object."""
    try:
        return getattr(issue.fields, field_id, None)
    except Exception:
        logger.debug(
            "Failed to read field %r from issue %r",
            field_id,
            getattr(issue, "key", "?"),
            exc_info=True,
        )
        return None


def _get_request_type(
    issue: Issue,
    request_type_field_id: str | None = None,
) -> str | None:
    """Extract the JSM request type name from an issue, if present."""
    try:
        rt = getattr(issue.fields, "requestType", None)
        if rt is not None:
            return getattr(rt, "name", None) or None

        if request_type_field_id:
            raw_fields: dict[str, Any] = (
                issue.raw.get("fields", {}) if isinstance(issue.raw, dict) else {}
            )
            fval = raw_fields.get(request_type_field_id)
            if isinstance(fval, dict):
                rt_dict = fval.get("requestType")
                if isinstance(rt_dict, dict):
                    name = rt_dict.get("name")
                    if name:
                        return str(name)
    except Exception:
        logger.debug(
            "Failed to extract request type from issue %r",
            getattr(issue, "key", "?"),
            exc_info=True,
        )
    return None


def _get_service_desk_id(issue: Issue) -> str | None:
    """Extract the numeric service desk ID from the issue, if present."""
    try:
        sd = getattr(issue.fields, "serviceDeskId", None)
        if sd is not None:
            return str(sd)
    except Exception:
        logger.debug(
            "Failed to extract serviceDeskId from issue %r",
            getattr(issue, "key", "?"),
            exc_info=True,
        )
    return None


# ---------------------------------------------------------------------------
# Connector class
# ---------------------------------------------------------------------------


class JiraServiceManagementConnector(JiraConnector):
    """JSM connector — subclasses JiraConnector, overrides only JSM-specific logic.

    Inherited from JiraConnector (no duplication):
      - All pagination, checkpoint, and bulk-fetch logic
      - Hierarchy node generation
      - ADF parsing and comment handling
      - validate_connector_settings
      - _get_project_permissions (now uses _get_document_source() hook)

    Overridden:
      - _get_document_source: returns JIRA_SERVICE_MANAGEMENT
      - _enrich_document: attaches SLA, request type, and service desk metadata
    """

    _MAX_SLA_DISCOVERY_ATTEMPTS: ClassVar[int] = 3

    def __init__(
        self,
        jira_base_url: str,
        project_key: str | None = None,
        comment_email_blacklist: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        labels_to_skip: list[str] = JIRA_CONNECTOR_LABELS_TO_SKIP,
        jql_query: str | None = None,
        scoped_token: bool = False,
    ) -> None:
        super().__init__(
            jira_base_url=jira_base_url,
            project_key=project_key,
            comment_email_blacklist=comment_email_blacklist,
            batch_size=batch_size,
            labels_to_skip=labels_to_skip,
            jql_query=jql_query,
            scoped_token=scoped_token,
        )
        # SLA discovery state — not present in parent
        self._sla_field_map: dict[str, str] | None = None
        self._sla_discovery_attempts: int = 0
        self._request_type_field_id: str | None = None
        self._fields_discovered: bool = False

    # ------------------------------------------------------------------
    # JiraConnector hooks
    # ------------------------------------------------------------------

    @override
    def _get_document_source(self) -> DocumentSource:
        return DocumentSource.JIRA_SERVICE_MANAGEMENT

    @override
    def _enrich_document(self, document: Document, issue: Any) -> Document:
        """Attach JSM-specific metadata (SLA, request type, service desk ID)."""
        try:
            self._ensure_fields_discovered()
        except Exception:
            logger.warning(
                "JSM field discovery raised unexpectedly for %r; "
                "SLA and JSM metadata will be skipped.",
                document.id,
                exc_info=True,
            )
            return document
        try:
            self._attach_sla_metadata(document, issue)
        except Exception:
            logger.warning(
                "Failed to attach SLA metadata to %r", document.id, exc_info=True
            )
        try:
            self._attach_jsm_metadata(document, issue)
        except Exception:
            logger.warning(
                "Failed to attach JSM metadata to %r", document.id, exc_info=True
            )
        return document

    # ------------------------------------------------------------------
    # Field discovery
    # ------------------------------------------------------------------

    def _ensure_fields_discovered(self) -> None:
        """Fetch the Jira field list once and populate SLA and request-type caches.

        429 (rate-limit) responses never consume a retry attempt — the method
        returns immediately so the caller can retry on the next document cycle.

        Non-429 API failures consume one attempt each. After reaching
        _MAX_SLA_DISCOVERY_ATTEMPTS, SLA enrichment is permanently disabled
        for this connector run (_sla_field_map set to empty dict).

        Helper calls (_discover_sla_mapping, _discover_request_type_mapping) are
        made directly with no wrapping try/except — any unexpected exception
        propagates to _enrich_document's guard, which logs a warning and returns
        the document unchanged so no documents are ever dropped.
        """
        if self._fields_discovered:
            return

        # ---- Rule 1: do NOT count 429s against the attempt cap ----
        try:
            all_fields: list[dict[str, Any]] = self.jira_client.fields()
        except Exception as e:
            is_rate_limited = getattr(e, "status_code", None) == 429
            if not is_rate_limited:
                self._sla_discovery_attempts += 1
            if is_rate_limited or self._sla_discovery_attempts < self._MAX_SLA_DISCOVERY_ATTEMPTS:
                logger.warning(
                    "JSM field fetch %s (attempt %d/%d) — will retry.",
                    "rate-limited (429)" if is_rate_limited else "failed",
                    self._sla_discovery_attempts,
                    self._MAX_SLA_DISCOVERY_ATTEMPTS,
                    exc_info=not is_rate_limited,
                )
                return   # no sleep — next document will retry
            else:
                logger.warning(
                    "JSM field fetch failed %d/%d times — SLA enrichment permanently disabled.",
                    self._sla_discovery_attempts,
                    self._MAX_SLA_DISCOVERY_ATTEMPTS,
                    exc_info=True,
                )
                self._sla_field_map = {}
                self._fields_discovered = True
                return

        # ---- Rule 2: call helpers directly — no outer try/except wrappers ----
        self._discover_sla_mapping(all_fields)
        self._discover_request_type_mapping(all_fields)
        self._fields_discovered = True

    def _discover_sla_mapping(self, all_fields: list[dict[str, Any]]) -> None:
        """Populate _sla_field_map from a pre-fetched field list."""
        mapping: dict[str, str] = {}
        try:
            for field_meta in all_fields:
                field_id: str = field_meta.get("id", "")
                field_name: str = field_meta.get("name", "")
                if not field_id.startswith("customfield_"):
                    continue
                for pattern, canonical_key in _COMPILED_SLA_PATTERNS:
                    if pattern.search(field_name):
                        mapping[field_id] = canonical_key
                        logger.debug(
                            "JSM SLA field discovered: %r (%r) → %r",
                            field_id,
                            field_name,
                            canonical_key,
                        )
                        break
            self._sla_field_map = mapping
        except Exception:
            logger.warning(
                "JSM SLA field processing failed after caching %d field(s).",
                len(mapping),
                exc_info=True,
            )
            self._sla_field_map = mapping

    def _discover_request_type_mapping(
        self, all_fields: list[dict[str, Any]]
    ) -> None:
        """Populate _request_type_field_id from a pre-fetched field list."""
        try:
            for field_meta in all_fields:
                field_id: str = field_meta.get("id", "")
                field_name: str = field_meta.get("name", "")
                if not field_id.startswith("customfield_"):
                    continue
                if _CUSTOMER_REQUEST_TYPE_PATTERN.search(field_name):
                    self._request_type_field_id = field_id
                    logger.debug(
                        "JSM request-type field discovered: %r (%r)",
                        field_id,
                        field_name,
                    )
                    break
        except Exception:
            logger.warning(
                "JSM request-type field processing failed.",
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # Document enrichment helpers
    # ------------------------------------------------------------------

    def _attach_sla_metadata(self, document: Document, issue: Issue) -> None:
        """Populate SLA-related keys in document.metadata."""
        sla_field_map = self._sla_field_map
        if not sla_field_map:
            if sla_field_map is None:
                logger.debug(
                    "SLA discovery not yet complete; skipping SLA enrichment for %r.",
                    document.id,
                )
            else:
                logger.debug(
                    "SLA field map is empty (no SLA fields found on this instance "
                    "or discovery permanently failed); skipping SLA enrichment for %r.",
                    document.id,
                )
            return

        for field_id, canonical_key in sla_field_map.items():
            raw_value = _get_raw_field(issue, field_id)
            if raw_value is None:
                continue
            display_str, is_breached = _extract_sla_display(raw_value)
            if display_str is not None:
                document.metadata[canonical_key] = display_str
            if is_breached:
                document.metadata[canonical_key + _BREACH_SUFFIX] = "true"

    def _attach_jsm_metadata(self, document: Document, issue: Issue) -> None:
        """Populate non-SLA JSM-specific metadata keys."""
        request_type = _get_request_type(issue, self._request_type_field_id)
        if request_type:
            document.metadata[_META_REQUEST_TYPE] = request_type

        service_desk_id = _get_service_desk_id(issue)
        if service_desk_id:
            document.metadata[_META_SERVICE_DESK] = service_desk_id
