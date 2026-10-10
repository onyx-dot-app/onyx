"""Auto-discovering coverage harness for source operations.

For every registered gateway, every (operation, variant) unit must be exercised,
per capability tag, by a capability check of that capability -- unless the
operation carries an ``untested`` reason. A per-connector session that registers
a gateway is picked up here automatically; it cannot forget to wire the test.
"""

from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.registry import get_capability_checks
from onyx.connectors.confluence.source_operations import (
    ConfluenceRestSpacePermissionsNotAvailableError,
    ConfluenceSpacePermissionsVariant,
)
from onyx.connectors.jira.models import JiraGroupPage, JiraIssueIdPage
from onyx.connectors.source_operations import (
    SourceOperations,
    registered_source_operations,
)
from tests.unit.onyx.connectors.source_operation_harnesses import (
    compute_uncovered_units,
    import_all_source_operation_gateways,
)

import_all_source_operation_gateways()


def _configure_confluence_spy(spy: MagicMock) -> None:
    """A DC 9.1+ site whose REST space-permissions endpoint is missing: the
    checks try REST and then fall back to JSON-RPC, so both DC units run."""

    def get_space_permissions(
        *, variant: ConfluenceSpacePermissionsVariant, **_kwargs: Any
    ) -> list[dict[str, Any]]:
        if variant == ConfluenceSpacePermissionsVariant.DC_REST:
            raise ConfluenceRestSpacePermissionsNotAvailableError("coverage spy")
        return []

    spy.get_server_version.return_value = (9, 1)
    spy.get_space_permissions.side_effect = get_space_permissions


def _configure_jira_site(spy: MagicMock) -> None:
    """A project that grants Browse Projects to a role with one user, and a
    group with one member, so the permission checks reach every read."""
    spy.list_projects.return_value = [{"key": "AS"}]
    spy.get_project_permission_scheme.return_value = {
        "permissions": [
            {
                "permission": "BROWSE_PROJECTS",
                "holder": {"type": "projectRole", "value": "10003"},
            }
        ]
    }
    spy.get_project_role.return_value = {
        "actors": [{"actorUser": {"accountId": "a1", "name": "a1"}}]
    }
    spy.list_groups.return_value = JiraGroupPage(group_names=["devs"], total=1)
    spy.get_group_members_page.return_value = {"values": [{"name": "a1"}]}
    # A safe tiny attachment exercises the optional JSM read probe without
    # changing the pass criteria for ordinary Jira indexing.
    issue = {"key": "AS-1", "fields": {"summary": "Issue"}}
    spy.search_issue_ids.return_value = JiraIssueIdPage(
        issue_ids=["1"], next_page_token=None
    )
    spy.bulk_fetch_issues.return_value = [issue]
    spy.search_issues.return_value = [issue]
    spy.list_fields.return_value = [{"id": "summary", "name": "Summary"}]
    spy.list_issue_attachments.return_value = [{"id": "att-1", "size": 1}]
    spy.download_attachment.return_value = b"x"


def _configure_jira_cloud_spy(spy: MagicMock) -> None:
    """A Cloud credential: the checks search with enhanced search and bulk
    fetch."""
    _configure_jira_site(spy)
    spy._is_cloud.return_value = True


def _configure_jira_server_spy(spy: MagicMock) -> None:
    """A Data Center credential: the checks search with the v2 search."""
    _configure_jira_site(spy)
    spy._is_cloud.return_value = False


# A unit is covered when the checks exercise it under any one configuration:
# a source whose credential picks the API family needs one per family.
_SPY_CONFIGURATIONS: dict[DocumentSource, list[Callable[[MagicMock], None]]] = {
    DocumentSource.CONFLUENCE: [_configure_confluence_spy],
    DocumentSource.JIRA: [_configure_jira_cloud_spy, _configure_jira_server_spy],
}


@pytest.mark.usefixtures("enable_ee")
@pytest.mark.parametrize(
    "gateway_class",
    list(registered_source_operations().values()),
    ids=lambda gateway_class: gateway_class.source.value,
)
def test_every_operation_unit_is_exercised_by_a_check(
    gateway_class: type[SourceOperations],
) -> None:
    """Verifies check coverage of every non-exempt (operation, variant) unit.

    Runs with EE enabled: perm-sync checks live only in the EE registries, so
    perm-sync-tagged units are coverable only when EE resolution is on.
    """
    # Precondition.
    checks = get_capability_checks(gateway_class.source)

    # Under test.
    configurations = _SPY_CONFIGURATIONS.get(gateway_class.source) or [None]
    uncovered = set.intersection(
        *(
            set(compute_uncovered_units(gateway_class, checks, configure_spy))
            for configure_spy in configurations
        )
    )

    # Postcondition.
    assert not uncovered, (
        f"{gateway_class.source.value} has operation units no capability "
        f"check exercises: {uncovered}. Add a check composing them "
        '(variant-bearing operations must be invoked with variant="<name>") '
        'or annotate the operation untested="<reason>".'
    )
