"""
Unit tests for the Jira Service Management connector.

Coverage targets
----------------
* Source tagging (all documents tagged with JIRA_SERVICE_MANAGEMENT)
* Dynamic SLA field discovery — success, partial match, API failure, caching
* SLA value extraction — Cloud nested dict, Server plain-string, breach flags,
  completed cycles, None / unknown shapes
* Document enrichment via _enrich_document hook
* JSM metadata (request type, service desk ID)
* doc_sync URL validation (P1 fix)
* Interface smoke tests (instantiation, load_credentials)

Note on imports of private helpers
-----------------------------------
``_extract_sla_display``, ``_get_raw_field``, ``_get_request_type``, and
``_get_service_desk_id`` are module-level private functions containing
non-trivial logic that is important to verify in isolation.  Direct import
is accepted in unit tests for the module that owns these helpers — the
alternative of testing only through ``_enrich_document`` would make each
test significantly harder to read and debug.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch as mock_patch

import pytest

import onyx.connectors.jira.connector as jira_module

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira_service_management.connector import _extract_sla_display
from onyx.connectors.jira_service_management.connector import _get_raw_field
from onyx.connectors.jira_service_management.connector import _get_request_type
from onyx.connectors.jira_service_management.connector import _get_service_desk_id
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from tests.unit.onyx.connectors.jira_service_management.conftest import make_mock_issue


# ─────────────────────────────────────────────────────────────────────────────
# Module-level helpers shared across test classes
# ─────────────────────────────────────────────────────────────────────────────


def _make_doc(doc_id: str = "https://example.atlassian.net/browse/HELP-1") -> Document:
    return Document(
        id=doc_id,
        sections=[TextSection(link=doc_id, text="some content")],
        source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
        semantic_identifier="HELP-1: Need help",
        title="HELP-1 Need help",
        metadata={},
    )


def _make_field_meta(field_id: str, name: str) -> dict[str, Any]:
    """Build a minimal Jira field metadata dict as returned by jira_client.fields()."""
    return {"id": field_id, "name": name, "schema": {"type": "any"}}


def _call_validate_jsm_config(config: dict[str, Any]) -> None:
    """Call _validate_jsm_config; skips silently if the EE module is unavailable."""
    try:
        from ee.onyx.external_permissions.jira_service_management.doc_sync import (
            _validate_jsm_config,
        )
    except ModuleNotFoundError:
        pytest.skip("EE module not available in this environment")
        return

    _validate_jsm_config(config)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Instantiation and source attribute
# ─────────────────────────────────────────────────────────────────────────────


class TestInstantiation:
    def test_process_jira_issue_called_with_jsm_source(
        self, jsm_connector: JiraServiceManagementConnector
    ) -> None:
        """process_jira_issue must be called with source=JIRA_SERVICE_MANAGEMENT.

        FIX (was broken in 3 ways):
        1. process_jira_issue lives in onyx.connectors.jira.connector (the base
           module), NOT in the JSM module — patching the JSM module namespace
           would have raised AttributeError at context-manager entry because the
           function is never imported there.
        2. wraps= must reference the function from the module being patched so
           the real implementation is still exercised while the spy records calls.
        3. The original ``if spy.call_count > 0`` guard let the test pass silently
           even when the code path was never exercised.  Replaced with a hard
           ``assert`` so the test fails loudly if no call is made.
        """
        mock_issue = make_mock_issue()
        jsm_connector._jira_client._options = {"rest_api_version": "2"}
        jsm_connector._jira_client.search_issues.return_value = [mock_issue]

        with mock_patch.object(
            jira_module,
            "process_jira_issue",
            wraps=jira_module.process_jira_issue,
        ) as spy:
            list(
                jsm_connector.load_from_checkpoint(
                    start=0,
                    end=9_999_999_999,
                    checkpoint=jsm_connector.build_dummy_checkpoint(),
                )
            )

        # Hard assertion — the test must fail if process_jira_issue was never called.
        assert spy.call_count > 0, (
            "process_jira_issue was never called during load_from_checkpoint. "
            "Either the mock issue was not processed or the code path changed."
        )
        _, kwargs = spy.call_args
        assert kwargs.get("source") is DocumentSource.JIRA_SERVICE_MANAGEMENT, (
            f"Expected source=JIRA_SERVICE_MANAGEMENT, got {kwargs.get('source')!r}"
        )

    def test_sla_field_map_starts_as_none(
        self, jsm_connector: JiraServiceManagementConnector
    ) -> None:
        assert jsm_connector._sla_field_map is None

    def test_request_type_field_id_starts_as_none(
        self, jsm_connector: JiraServiceManagementConnector
    ) -> None:
        assert jsm_connector._request_type_field_id is None

    def test_sla_discovery_attempts_starts_at_zero(
        self, jsm_connector: JiraServiceManagementConnector
    ) -> None:
        assert jsm_connector._sla_discovery_attempts == 0

    def test_implements_required_interfaces(
        self, jsm_connector: JiraServiceManagementConnector
    ) -> None:
        """Connector must implement required interfaces and subclass JiraConnector."""
        from onyx.connectors.interfaces import CheckpointedConnectorWithPermSync
        from onyx.connectors.interfaces import SlimConnectorWithPermSync
        from onyx.connectors.jira.connector import JiraConnector

        assert isinstance(jsm_connector, CheckpointedConnectorWithPermSync)
        assert isinstance(jsm_connector, SlimConnectorWithPermSync)
        assert isinstance(jsm_connector, JiraConnector)  # now TRUE after refactor

    def test_project_key_stored(
        self, jsm_connector: JiraServiceManagementConnector
    ) -> None:
        assert jsm_connector.jira_project == "HELP"

    def test_base_url_stored(
        self, jsm_connector: JiraServiceManagementConnector
    ) -> None:
        assert jsm_connector.jira_base == "https://example.atlassian.net"

    def test_jsm_init_adds_sla_state(
        self, jsm_connector: JiraServiceManagementConnector
    ) -> None:
        """Parent __init__ must run AND JSM SLA state must be initialized."""
        # Parent state (from JiraConnector)
        assert jsm_connector.jira_base == "https://example.atlassian.net"
        assert jsm_connector.jira_project == "HELP"
        # JSM-specific state
        assert jsm_connector._sla_field_map is None
        assert jsm_connector._sla_discovery_attempts == 0
        assert jsm_connector._request_type_field_id is None
        assert jsm_connector._fields_discovered is False

    def test_get_document_source_returns_jsm(
        self, jsm_connector: JiraServiceManagementConnector
    ) -> None:
        """_get_document_source must return JIRA_SERVICE_MANAGEMENT."""
        assert (
            jsm_connector._get_document_source()
            is DocumentSource.JIRA_SERVICE_MANAGEMENT
        )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Dynamic field discovery — _ensure_fields_discovered
# ─────────────────────────────────────────────────────────────────────────────


class TestSLAFieldDiscovery:
    def test_discovers_time_to_first_response(
        self, jsm_connector: JiraServiceManagementConnector, mock_jira_client: MagicMock
    ) -> None:
        mock_jira_client.fields.return_value = [
            _make_field_meta("customfield_10020", "Time to first response"),
            _make_field_meta("summary", "Summary"),  # non-custom — must be ignored
        ]
        jsm_connector._ensure_fields_discovered()
        assert jsm_connector._sla_field_map == {
            "customfield_10020": "sla_time_to_first_response"
        }

    def test_discovers_time_to_resolution(
        self, jsm_connector: JiraServiceManagementConnector, mock_jira_client: MagicMock
    ) -> None:
        mock_jira_client.fields.return_value = [
            _make_field_meta("customfield_10030", "Time to resolution"),
        ]
        jsm_connector._ensure_fields_discovered()
        assert jsm_connector._sla_field_map is not None
        assert "customfield_10030" in jsm_connector._sla_field_map
        assert (
            jsm_connector._sla_field_map["customfield_10030"] == "sla_time_to_resolution"
        )

    def test_discovery_is_case_insensitive(
        self, jsm_connector: JiraServiceManagementConnector, mock_jira_client: MagicMock
    ) -> None:
        mock_jira_client.fields.return_value = [
            _make_field_meta("customfield_10050", "TIME TO FIRST RESPONSE"),
        ]
        jsm_connector._ensure_fields_discovered()
        assert jsm_connector._sla_field_map is not None
        assert "customfield_10050" in jsm_connector._sla_field_map

    def test_non_customfield_ids_are_ignored(
        self, jsm_connector: JiraServiceManagementConnector, mock_jira_client: MagicMock
    ) -> None:
        mock_jira_client.fields.return_value = [
            _make_field_meta("summary", "Time to first response"),
            _make_field_meta("description", "Time to resolution"),
        ]
        jsm_connector._ensure_fields_discovered()
        assert jsm_connector._sla_field_map == {}

    def test_empty_fields_returns_empty_map(
        self, jsm_connector: JiraServiceManagementConnector, mock_jira_client: MagicMock
    ) -> None:
        mock_jira_client.fields.return_value = []
        jsm_connector._ensure_fields_discovered()
        assert jsm_connector._sla_field_map == {}

    def test_api_failure_leaves_map_as_none_before_cap(
        self, jsm_connector: JiraServiceManagementConnector, mock_jira_client: MagicMock
    ) -> None:
        mock_jira_client.fields.side_effect = RuntimeError("API down")
        jsm_connector._ensure_fields_discovered()
        # _sla_field_map remains None while retries are still permitted
        assert jsm_connector._sla_field_map is None

    def test_api_failure_caches_empty_map_after_cap(
        self, jsm_connector: JiraServiceManagementConnector, mock_jira_client: MagicMock
    ) -> None:
        mock_jira_client.fields.side_effect = RuntimeError("API down")
        # Set attempts to just before the cap so the next call hits it.
        jsm_connector._sla_discovery_attempts = (
            jsm_connector._MAX_SLA_DISCOVERY_ATTEMPTS - 1
        )
        jsm_connector._ensure_fields_discovered()
        assert jsm_connector._sla_field_map == {}

    def test_discovery_cached_after_first_call(
        self, jsm_connector: JiraServiceManagementConnector, mock_jira_client: MagicMock
    ) -> None:
        mock_jira_client.fields.return_value = [
            _make_field_meta("customfield_10020", "Time to first response"),
        ]
        jsm_connector._ensure_fields_discovered()
        first_map = jsm_connector._sla_field_map

        jsm_connector._ensure_fields_discovered()
        second_map = jsm_connector._sla_field_map

        # The API must be called exactly once — second call hits the fast-path.
        mock_jira_client.fields.assert_called_once()
        # Same dict object from cache (identity check, not just equality).
        assert first_map is second_map

    def test_discovers_multiple_sla_fields(
        self, jsm_connector: JiraServiceManagementConnector, mock_jira_client: MagicMock
    ) -> None:
        mock_jira_client.fields.return_value = [
            _make_field_meta("customfield_10020", "Time to first response"),
            _make_field_meta("customfield_10030", "Time to resolution"),
            _make_field_meta("customfield_10040", "Time to close"),
        ]
        jsm_connector._ensure_fields_discovered()
        assert jsm_connector._sla_field_map is not None
        assert len(jsm_connector._sla_field_map) == 3
        assert (
            jsm_connector._sla_field_map["customfield_10020"]
            == "sla_time_to_first_response"
        )
        assert (
            jsm_connector._sla_field_map["customfield_10030"] == "sla_time_to_resolution"
        )
        assert jsm_connector._sla_field_map["customfield_10040"] == "sla_time_to_close"

    def test_discovers_customer_request_type_field(
        self, jsm_connector: JiraServiceManagementConnector, mock_jira_client: MagicMock
    ) -> None:
        mock_jira_client.fields.return_value = [
            _make_field_meta("customfield_10010", "Customer Request Type"),
            _make_field_meta("customfield_10020", "Time to first response"),
        ]
        jsm_connector._ensure_fields_discovered()
        assert jsm_connector._request_type_field_id == "customfield_10010"

    def test_request_type_discovery_is_case_insensitive(
        self, jsm_connector: JiraServiceManagementConnector, mock_jira_client: MagicMock
    ) -> None:
        mock_jira_client.fields.return_value = [
            _make_field_meta("customfield_10010", "CUSTOMER REQUEST TYPE"),
        ]
        jsm_connector._ensure_fields_discovered()
        assert jsm_connector._request_type_field_id == "customfield_10010"

    def test_sla_processing_failure_propagates_from_ensure(
        self, jsm_connector: JiraServiceManagementConnector, mock_jira_client: MagicMock
    ) -> None:
        """Rule 2: helpers are called directly (no outer try/except).
        A failure in _discover_sla_mapping propagates out of _ensure_fields_discovered.
        The outer guard in _enrich_document catches it so no document is dropped,
        but _ensure_fields_discovered itself re-raises."""
        mock_jira_client.fields.return_value = [
            _make_field_meta("customfield_10010", "Customer Request Type"),
        ]
        with mock_patch.object(
            jsm_connector,
            "_discover_sla_mapping",
            side_effect=RuntimeError("SLA processing error"),
        ):
            with pytest.raises(RuntimeError, match="SLA processing error"):
                jsm_connector._ensure_fields_discovered()

        # _fields_discovered stays False because the exception interrupted the flow.
        assert jsm_connector._fields_discovered is False

    def test_single_api_call_regardless_of_both_helpers(
        self, jsm_connector: JiraServiceManagementConnector, mock_jira_client: MagicMock
    ) -> None:
        """The field list is fetched exactly once even though two helpers process it."""
        mock_jira_client.fields.return_value = [
            _make_field_meta("customfield_10010", "Customer Request Type"),
            _make_field_meta("customfield_10020", "Time to first response"),
        ]
        jsm_connector._ensure_fields_discovered()
        mock_jira_client.fields.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# 3. SLA value extraction (_extract_sla_display)
# ─────────────────────────────────────────────────────────────────────────────


class TestExtractSLADisplay:
    def test_none_returns_none_not_breached(self) -> None:
        display, breached = _extract_sla_display(None)
        assert display is None
        assert breached is False

    def test_plain_string_returns_as_is(self) -> None:
        display, breached = _extract_sla_display("2h 30m")
        assert display == "2h 30m"
        assert breached is False

    def test_empty_string_returns_none(self) -> None:
        display, breached = _extract_sla_display("")
        assert display is None
        assert breached is False

    def test_server_dc_simple_dict(self) -> None:
        sla = {"text": "1h 15m", "breached": False}
        display, breached = _extract_sla_display(sla)
        assert display == "1h 15m"
        assert breached is False

    def test_server_dc_breached_dict(self) -> None:
        sla = {"text": "Breached", "breached": True}
        display, breached = _extract_sla_display(sla)
        assert display == "Breached"
        assert breached is True

    def test_cloud_ongoing_cycle_not_breached(self) -> None:
        sla = {
            "ongoingCycle": {
                "remainingTime": {"friendly": "3h 0m", "millis": 10800000},
                "breached": False,
                "paused": False,
            }
        }
        display, breached = _extract_sla_display(sla)
        assert display == "3h 0m"
        assert breached is False

    def test_cloud_ongoing_cycle_breached(self) -> None:
        sla = {
            "ongoingCycle": {
                "remainingTime": {"friendly": "", "millis": -3600000},
                "breached": True,
            }
        }
        display, breached = _extract_sla_display(sla)
        # friendly is empty so falls back to "Breached"
        assert display == "Breached"
        assert breached is True

    def test_cloud_completed_cycle(self) -> None:
        sla = {
            "completedCycles": [
                {
                    "remainingTime": {"friendly": "0h 30m"},
                    "breached": False,
                },
            ]
        }
        display, breached = _extract_sla_display(sla)
        assert display == "0h 30m"
        assert breached is False

    def test_cloud_completed_cycle_breached(self) -> None:
        sla = {
            "completedCycles": [
                {
                    "remainingTime": {"friendly": ""},
                    "breached": True,
                },
            ]
        }
        display, breached = _extract_sla_display(sla)
        assert breached is True

    def test_unknown_type_returns_none(self) -> None:
        display, breached = _extract_sla_display(12345)  # type: ignore[arg-type]
        assert display is None
        assert breached is False

    def test_empty_dict_returns_none(self) -> None:
        display, breached = _extract_sla_display({})
        assert display is None
        assert breached is False


# ─────────────────────────────────────────────────────────────────────────────
# 4. Document enrichment — _enrich_document hook
# ─────────────────────────────────────────────────────────────────────────────


class TestEnrichDocument:
    def test_source_is_jsm_on_enriched_document(
        self, jsm_connector: JiraServiceManagementConnector
    ) -> None:
        """Document source must be JIRA_SERVICE_MANAGEMENT, not JIRA."""
        jsm_connector._sla_field_map = {}  # skip discovery
        doc = _make_doc()
        issue = make_mock_issue()
        result = jsm_connector._enrich_document(doc, issue)
        assert result.source is DocumentSource.JIRA_SERVICE_MANAGEMENT

    def test_sla_metadata_attached_when_field_present(
        self, jsm_connector: JiraServiceManagementConnector
    ) -> None:
        jsm_connector._sla_field_map = {
            "customfield_10020": "sla_time_to_first_response",
        }
        sla_value = {"text": "2h 0m", "breached": False}
        issue = make_mock_issue(extra_fields={"customfield_10020": sla_value})
        doc = _make_doc()
        result = jsm_connector._enrich_document(doc, issue)
        assert result.metadata.get("sla_time_to_first_response") == "2h 0m"

    def test_breach_flag_attached_when_breached(
        self, jsm_connector: JiraServiceManagementConnector
    ) -> None:
        jsm_connector._sla_field_map = {
            "customfield_10020": "sla_time_to_first_response",
        }
        sla_value = {"text": "Breached", "breached": True}
        issue = make_mock_issue(extra_fields={"customfield_10020": sla_value})
        doc = _make_doc()
        result = jsm_connector._enrich_document(doc, issue)
        assert result.metadata.get("sla_time_to_first_response_breached") == "true"

    def test_no_breach_flag_when_not_breached(
        self, jsm_connector: JiraServiceManagementConnector
    ) -> None:
        jsm_connector._sla_field_map = {
            "customfield_10020": "sla_time_to_first_response",
        }
        sla_value = {"text": "1h", "breached": False}
        issue = make_mock_issue(extra_fields={"customfield_10020": sla_value})
        doc = _make_doc()
        result = jsm_connector._enrich_document(doc, issue)
        assert "sla_time_to_first_response_breached" not in result.metadata

    def test_multiple_sla_fields_all_attached(
        self, jsm_connector: JiraServiceManagementConnector
    ) -> None:
        jsm_connector._sla_field_map = {
            "customfield_10020": "sla_time_to_first_response",
            "customfield_10030": "sla_time_to_resolution",
        }
        issue = make_mock_issue(
            extra_fields={
                "customfield_10020": {"text": "2h", "breached": False},
                "customfield_10030": {"text": "4h", "breached": False},
            }
        )
        doc = _make_doc()
        result = jsm_connector._enrich_document(doc, issue)
        assert "sla_time_to_first_response" in result.metadata
        assert "sla_time_to_resolution" in result.metadata

    def test_missing_sla_field_on_issue_does_not_add_metadata(
        self, jsm_connector: JiraServiceManagementConnector
    ) -> None:
        jsm_connector._sla_field_map = {
            "customfield_10020": "sla_time_to_first_response",
        }
        # customfield_10020 not in extra_fields and not accessible on issue.fields
        # (because spec=_FieldsSpec prevents auto-creation of unknown attributes)
        issue = make_mock_issue()
        doc = _make_doc()
        result = jsm_connector._enrich_document(doc, issue)
        assert "sla_time_to_first_response" not in result.metadata

    def test_sla_error_does_not_drop_document(
        self, jsm_connector: JiraServiceManagementConnector
    ) -> None:
        """A bad SLA value must never cause the document to be dropped."""
        jsm_connector._sla_field_map = {
            "customfield_10020": "sla_time_to_first_response",
        }
        # object() is not str or dict — _extract_sla_display returns (None, False).
        broken_sla = object()
        issue = make_mock_issue(extra_fields={"customfield_10020": broken_sla})
        doc = _make_doc()
        # Must not raise; document must be returned; metadata must not be corrupted.
        result = jsm_connector._enrich_document(doc, issue)
        assert result is not None
        assert "sla_time_to_first_response" not in result.metadata

    def test_empty_sla_map_skips_sla_enrichment(
        self, jsm_connector: JiraServiceManagementConnector
    ) -> None:
        jsm_connector._sla_field_map = {}
        issue = make_mock_issue()
        doc = _make_doc()
        result = jsm_connector._enrich_document(doc, issue)
        sla_keys = [k for k in result.metadata if k.startswith("sla_")]
        assert sla_keys == []

    def test_returns_same_document_object(
        self, jsm_connector: JiraServiceManagementConnector
    ) -> None:
        jsm_connector._sla_field_map = {}
        doc = _make_doc()
        issue = make_mock_issue()
        result = jsm_connector._enrich_document(doc, issue)
        assert result is doc

    def test_single_discovery_call_per_enrich(
        self, jsm_connector: JiraServiceManagementConnector, mock_jira_client: MagicMock
    ) -> None:
        """_ensure_fields_discovered must be called exactly once per _enrich_document
        invocation regardless of how many metadata helpers execute."""
        mock_jira_client.fields.return_value = []
        doc = _make_doc()
        issue = make_mock_issue()
        jsm_connector._enrich_document(doc, issue)
        # The underlying API call must happen exactly once even though both
        # _attach_sla_metadata and _attach_jsm_metadata run.
        mock_jira_client.fields.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# 5. JSM metadata helpers
# ─────────────────────────────────────────────────────────────────────────────


class TestJSMMetadataHelpers:
    def test_get_raw_field_returns_value(self) -> None:
        issue = make_mock_issue(extra_fields={"customfield_10020": "2h"})
        assert _get_raw_field(issue, "customfield_10020") == "2h"

    def test_get_raw_field_missing_returns_none(self) -> None:
        # spec=_FieldsSpec on issue.fields means undefined customfields raise
        # AttributeError, which _get_raw_field's getattr(…, None) catches and
        # returns None.
        issue = make_mock_issue()
        assert _get_raw_field(issue, "customfield_99999") is None

    def test_get_request_type_from_cloud_field(self) -> None:
        issue = make_mock_issue()
        rt = MagicMock()
        rt.name = "IT Support"
        issue.fields.requestType = rt
        assert _get_request_type(issue) == "IT Support"

    def test_get_request_type_returns_none_when_name_is_none(self) -> None:
        """If requestType.name is None, return None — not a Python object repr."""
        issue = make_mock_issue()
        rt = MagicMock()
        rt.name = None
        issue.fields.requestType = rt
        assert _get_request_type(issue) is None

    def test_get_request_type_missing_returns_none(self) -> None:
        issue = make_mock_issue()
        issue.fields.requestType = None
        assert _get_request_type(issue) is None

    def test_get_request_type_server_dc_targeted_lookup(self) -> None:
        """Server/DC path uses only the provided field ID, not a blind scan."""
        issue = make_mock_issue()
        issue.fields.requestType = None
        issue.raw = {
            "fields": {
                "customfield_10010": {"requestType": {"name": "Password Reset"}},
                # This field also has requestType but must NOT be matched.
                "customfield_99999": {"requestType": {"name": "Wrong Type"}},
            }
        }
        result = _get_request_type(issue, request_type_field_id="customfield_10010")
        assert result == "Password Reset"

    def test_get_request_type_no_field_id_skips_server_dc_path(self) -> None:
        """Without a field ID, the Server/DC path is not attempted at all."""
        issue = make_mock_issue()
        issue.fields.requestType = None
        issue.raw = {
            "fields": {
                "customfield_10010": {"requestType": {"name": "Password Reset"}},
            }
        }
        # No request_type_field_id provided — must return None even though the
        # field exists in raw, because blind scanning is intentionally disabled.
        assert _get_request_type(issue) is None

    def test_get_service_desk_id_absent_returns_none(self) -> None:
        issue = make_mock_issue(project_key="HELP")
        issue.fields.serviceDeskId = None
        assert _get_service_desk_id(issue) is None

    def test_get_service_desk_id_returns_string(self) -> None:
        issue = make_mock_issue()
        issue.fields.serviceDeskId = 42  # numeric — must be stringified
        assert _get_service_desk_id(issue) == "42"

    def test_jsm_metadata_attached_to_document(
        self, jsm_connector: JiraServiceManagementConnector
    ) -> None:
        jsm_connector._sla_field_map = {}
        issue = make_mock_issue(project_key="SD")
        issue.fields.serviceDeskId = "SD"
        rt = MagicMock()
        rt.name = "Password Reset"
        issue.fields.requestType = rt
        doc = _make_doc()
        result = jsm_connector._enrich_document(doc, issue)
        assert result.metadata.get("jsm_request_type") == "Password Reset"
        assert result.metadata.get("jsm_service_desk_id") == "SD"


# ─────────────────────────────────────────────────────────────────────────────
# 6. doc_sync URL validation (EE-only)
#
# Rule 4: pytest.importorskip is scoped INSIDE this class via an autouse
# fixture so that CE tests (TestInstantiation, TestSLAFieldDiscovery, etc.)
# run freely in Community Edition environments.
# ─────────────────────────────────────────────────────────────────────────────


class TestDocSyncURLValidation:
    @pytest.fixture(autouse=True)
    def _require_ee_module(self) -> None:  # type: ignore[return]
        """Skip every test in this class if the EE doc_sync module is absent."""
        pytest.importorskip(
            "ee.onyx.external_permissions.jira_service_management.doc_sync",
            reason="EE module not available in this environment",
        )

    def test_valid_https_url_passes(self) -> None:
        _call_validate_jsm_config({"jira_base_url": "https://example.atlassian.net"})

    def test_valid_http_url_passes(self) -> None:
        _call_validate_jsm_config({"jira_base_url": "http://jira.internal.corp"})

    def test_missing_key_raises(self) -> None:
        from onyx.connectors.exceptions import ConnectorValidationError

        with pytest.raises(ConnectorValidationError, match="jira_base_url"):
            _call_validate_jsm_config({})

    def test_empty_string_raises(self) -> None:
        from onyx.connectors.exceptions import ConnectorValidationError

        with pytest.raises(ConnectorValidationError, match="non-empty"):
            _call_validate_jsm_config({"jira_base_url": ""})

    def test_whitespace_only_raises(self) -> None:
        from onyx.connectors.exceptions import ConnectorValidationError

        with pytest.raises(ConnectorValidationError, match="non-empty"):
            _call_validate_jsm_config({"jira_base_url": "   "})

    def test_url_without_scheme_raises(self) -> None:
        from onyx.connectors.exceptions import ConnectorValidationError

        with pytest.raises(ConnectorValidationError, match="http"):
            _call_validate_jsm_config({"jira_base_url": "example.atlassian.net"})

    def test_non_string_value_raises(self) -> None:
        from onyx.connectors.exceptions import ConnectorValidationError

        with pytest.raises(ConnectorValidationError):
            _call_validate_jsm_config({"jira_base_url": 12345})


# ─────────────────────────────────────────────────────────────────────────────
# 7. Cloud SLA format — extended edge cases
# ─────────────────────────────────────────────────────────────────────────────


class TestCloudSLAEdgeCases:
    def test_ongoing_cycle_missing_remainingTime_friendly(self) -> None:
        sla = {
            "ongoingCycle": {
                "remainingTime": {},  # no "friendly" key
                "breached": False,
            }
        }
        display, breached = _extract_sla_display(sla)
        assert display is None
        assert breached is False

    def test_ongoing_cycle_remainingTime_not_dict(self) -> None:
        sla = {
            "ongoingCycle": {
                "remainingTime": "1h",  # Server-style string inside Cloud wrapper
                "breached": False,
            }
        }
        display, breached = _extract_sla_display(sla)
        # remainingTime is not a dict so friendly cannot be extracted
        assert display is None

    def test_multiple_completed_cycles_uses_last(self) -> None:
        sla = {
            "completedCycles": [
                {"remainingTime": {"friendly": "old"}, "breached": False},
                {"remainingTime": {"friendly": "newest"}, "breached": True},
            ]
        }
        display, breached = _extract_sla_display(sla)
        assert display == "newest"
        assert breached is True

    def test_empty_completedCycles_list(self) -> None:
        sla = {"completedCycles": []}
        display, breached = _extract_sla_display(sla)
        assert display is None
        assert breached is False
