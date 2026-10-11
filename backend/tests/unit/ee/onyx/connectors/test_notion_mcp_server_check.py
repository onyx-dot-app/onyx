"""The EE registry appends Notion's per-user MCP server check to its INDEXING
checks for permission-synced access types. EE is on for this directory; the CE
registry test proves CE builds never see it."""

from unittest.mock import MagicMock, patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
)
from onyx.connectors.capability_checks.registry import get_capability_checks
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.notion.source_operations import NotionSourceOperations
from onyx.db.enums import AccessType

CHECK_ID = "notion_per_user_mcp_server"


def _notion_check() -> CapabilityCheck:
    checks: dict[str, CapabilityCheck] = {
        check.check_id: check for check in get_capability_checks(DocumentSource.NOTION)
    }
    return checks[CHECK_ID]


def _context() -> CapabilityCheckContext:
    return CapabilityCheckContext(
        source=DocumentSource.NOTION,
        credential_json={"notion_integration_token": "ntn_test"},
        source_operations=MagicMock(spec=NotionSourceOperations),
    )


def test_ee_registers_the_check_for_perm_synced_access_only() -> None:
    check: CapabilityCheck = _notion_check()
    assert check.access_types == frozenset(AccessType.perm_synced_types())
    assert check.required
    assert not check.requires_connector_instance


def test_missing_server_fails_the_check() -> None:
    with patch(
        "ee.onyx.connectors.capability_checks.raise_if_no_per_user_notion_mcp_server",
        side_effect=ConnectorValidationError("no server"),
    ):
        with pytest.raises(ConnectorValidationError, match="no server"):
            _notion_check().run(_context())


def test_registered_server_passes_the_check() -> None:
    with patch(
        "ee.onyx.connectors.capability_checks.raise_if_no_per_user_notion_mcp_server"
    ) as probe:
        _notion_check().run(_context())
    probe.assert_called_once_with()
