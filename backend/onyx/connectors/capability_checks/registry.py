from onyx.configs.constants import DocumentSource

# Re-exported: existing callers resolve applicability through the registry; the
# function lives in ``applicability`` so hot-path modules can import it without
# this module's eager per-connector check imports.
from onyx.connectors.capability_checks.applicability import (
    get_applicable_capabilities as get_applicable_capabilities,
)
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CredentialCapability,
)
from onyx.connectors.slack.capability_checks import build_slack_indexing_checks
from onyx.connectors.source_operations import get_source_operations_class
from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop

# INDEXING checks per source. Checks must be enumerable without an instantiated
# connector, hence a registry module rather than a ``BaseConnector`` method.
# Per-connector work registers named checks here.
_INDEXING_CHECKS_BY_SOURCE: dict[DocumentSource, list[CapabilityCheck]] = {
    DocumentSource.SLACK: build_slack_indexing_checks(),
}


class _ConnectorSettingsFallbackCheck(CapabilityCheck):
    """Baseline INDEXING check where the source registers no named checks.

    Wraps the legacy ``validate_connector_settings`` blob so every connector has
    day-one coverage until a per-connector session registers named,
    per-permission checks that shadow this.
    """

    def __init__(self, source: DocumentSource) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id=f"{source.value}_connector_settings",
            display_name="Connector settings validation",
            is_fallback=True,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        assert context.connector is not None, (
            "The runner guarantees an instance of a connector."
        )
        context.connector.validate_connector_settings()


def get_capability_checks(source: DocumentSource) -> list[CapabilityCheck]:
    """
    Returns all capability checks for a source, synthesizing fallbacks where
    there are no named checks.

    INDEXING checks are registered here; perm-sync checks come from the EE
    implementation and are empty on OSS builds, where the perm-sync feature does
    not exist.

    Ratchet: named checks require a registered source-operations gateway --
    participation in the checks system is an anti-drift guarantee. Unmigrated
    sources keep the fallback path.
    """
    checks = list(_INDEXING_CHECKS_BY_SOURCE.get(source, []))
    assert not checks or get_source_operations_class(source) is not None, (
        f"{source.value} registers named INDEXING checks but no "
        "source-operations gateway; migrate the connector first."
    )
    if not checks:
        checks.append(_ConnectorSettingsFallbackCheck(source))
    get_perm_sync_checks = fetch_ee_implementation_or_noop(
        "onyx.connectors.capability_checks",
        "get_perm_sync_capability_checks",
        noop_return_value=[],
    )
    checks.extend(get_perm_sync_checks(source))
    return checks
