from onyx.configs.constants import DocumentSource

# Re-exported: existing callers resolve applicability through the registry; the
# function lives in ``applicability`` so hot-path modules can import it without
# this module's eager per-connector check imports.
from onyx.connectors.capability_checks.applicability import (
    get_applicable_capabilities as get_applicable_capabilities,
)
from onyx.connectors.capability_checks.generic_row import (
    GENERIC_CHECK_NAME,
    GENERIC_PASS_LINE,
    generic_row_error,
)
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CheckOutput,
    CredentialCapability,
)
from onyx.connectors.confluence.capability_checks import (
    build_confluence_indexing_checks,
)
from onyx.connectors.factory import source_has_settings_probe
from onyx.connectors.github.capability_checks import build_github_indexing_checks
from onyx.connectors.google_drive.capability_checks import (
    build_google_drive_indexing_checks,
)
from onyx.connectors.hubspot.capability_checks import build_hubspot_indexing_checks
from onyx.connectors.jira.capability_checks import build_jira_indexing_checks
from onyx.connectors.linear.capability_checks import build_linear_indexing_checks
from onyx.connectors.notion.capability_checks import build_notion_indexing_checks
from onyx.connectors.onedrive.capability_checks import build_onedrive_indexing_checks
from onyx.connectors.outlook.capability_checks import build_outlook_indexing_checks
from onyx.connectors.sharepoint.capability_checks import (
    build_sharepoint_indexing_checks,
)
from onyx.connectors.slack.capability_checks import build_slack_indexing_checks
from onyx.connectors.source_operations import get_source_operations_class
from onyx.connectors.youtrack.capability_checks import (
    build_youtrack_indexing_checks,
)
from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop

# INDEXING checks per source. Checks must be enumerable without an instantiated
# connector, hence a registry module rather than a ``BaseConnector`` method.
# Per-connector work registers named checks here.
_INDEXING_CHECKS_BY_SOURCE: dict[DocumentSource, list[CapabilityCheck]] = {
    DocumentSource.SLACK: build_slack_indexing_checks(),
    DocumentSource.CONFLUENCE: build_confluence_indexing_checks(),
    DocumentSource.GOOGLE_DRIVE: build_google_drive_indexing_checks(),
    DocumentSource.ONEDRIVE: build_onedrive_indexing_checks(),
    DocumentSource.OUTLOOK: build_outlook_indexing_checks(),
    DocumentSource.HUBSPOT: build_hubspot_indexing_checks(),
    DocumentSource.JIRA: build_jira_indexing_checks(),
    DocumentSource.LINEAR: build_linear_indexing_checks(),
    DocumentSource.NOTION: build_notion_indexing_checks(),
    DocumentSource.SHAREPOINT: build_sharepoint_indexing_checks(),
    DocumentSource.GITHUB: build_github_indexing_checks(),
    DocumentSource.YOUTRACK: build_youtrack_indexing_checks(),
}


class _ConnectorSettingsFallbackCheck(CapabilityCheck):
    """The generic row, where the source registers no named INDEXING checks.

    Wraps the legacy ``validate_connector_settings`` probe until a
    per-connector session registers named checks that shadow this. Like a
    sign-in, it fails on a form run when the source does not answer.
    """

    def __init__(self, source: DocumentSource) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id=f"{source.value}_connector_settings",
            display_name=GENERIC_CHECK_NAME,
            is_fallback=True,
            fails_when_unreachable=True,
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        if context.connector is None:
            raise TypeError("Bug: The runner guarantees an instance of a connector.")
        try:
            context.connector.validate_connector_settings()
        except Exception as e:
            typed = generic_row_error(e)
            if typed is e:
                raise
            raise typed from e
        return CheckOutput(summary=GENERIC_PASS_LINE)


def get_capability_checks(source: DocumentSource) -> list[CapabilityCheck]:
    """
    Returns all capability checks for a source, synthesizing fallbacks where
    there are no named checks.

    INDEXING checks are registered here; perm-sync checks come from the EE
    implementation and are empty on OSS builds, where the perm-sync feature does
    not exist.

    A source whose connector has no settings probe gets no INDEXING check:
    a check that reaches nothing must not pass.

    Ratchet: named checks require a registered source-operations gateway --
    participation in the checks system is an anti-drift guarantee. Unmigrated
    sources keep the fallback path.
    """
    checks = list(_INDEXING_CHECKS_BY_SOURCE.get(source, []))
    assert not checks or get_source_operations_class(source) is not None, (
        f"{source.value} registers named INDEXING checks but no "
        "source-operations gateway; migrate the connector first."
    )
    if not checks and source_has_settings_probe(source):
        checks.append(_ConnectorSettingsFallbackCheck(source))
    get_perm_sync_checks = fetch_ee_implementation_or_noop(
        "onyx.connectors.capability_checks",
        "get_perm_sync_capability_checks",
        noop_return_value=[],
    )
    checks.extend(get_perm_sync_checks(source))
    return checks


def has_named_capability_checks(source: DocumentSource) -> bool:
    """True when the source registers named checks beyond the legacy fallback,
    so a full run reports more than the blocking validation already recorded."""
    return any(not check.is_fallback for check in get_capability_checks(source))
