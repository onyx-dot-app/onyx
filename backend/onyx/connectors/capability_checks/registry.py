from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CredentialCapability,
)
from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop

# INDEXING checks per source. Checks must be enumerable without an instantiated
# connector, hence a registry module rather than a ``BaseConnector`` method.
# Empty at framework stage: per-connector work registers named checks here.
_INDEXING_CHECKS_BY_SOURCE: dict[DocumentSource, list[CapabilityCheck]] = {}


def _run_connector_settings_fallback(context: CapabilityCheckContext) -> None:
    assert context.connector is not None, "The runner guarantees an instance."
    context.connector.validate_connector_settings()


def _build_indexing_fallback_check(source: DocumentSource) -> CapabilityCheck:
    """Builds the baseline INDEXING check for a source with no named checks.

    Wraps the legacy ``validate_connector_settings`` blob so every connector has
    day-one coverage until a per-connector session registers named,
    per-permission checks that shadow this.
    """
    return CapabilityCheck(
        capability=CredentialCapability.INDEXING,
        check_id=f"{source.value}_connector_settings",
        display_name="Connector settings validation",
        run=_run_connector_settings_fallback,
        is_fallback=True,
    )


def get_capability_checks(source: DocumentSource) -> list[CapabilityCheck]:
    """Returns all capability checks for a source, synthesizing fallbacks.

    INDEXING checks are registered here; perm-sync checks come from the EE hook
    and are empty on OSS builds, where the perm-sync feature does not exist.
    """
    checks = list(_INDEXING_CHECKS_BY_SOURCE.get(source, []))
    if not checks:
        checks.append(_build_indexing_fallback_check(source))
    get_perm_sync_checks = fetch_ee_implementation_or_noop(
        "onyx.connectors.capability_checks",
        "get_perm_sync_capability_checks",
        noop_return_value=[],
    )
    checks.extend(get_perm_sync_checks(source))
    return checks


def get_applicable_capabilities(source: DocumentSource) -> set[CredentialCapability]:
    """Returns the capabilities that exist for this source on this build.

    Capabilities outside this set aggregate to a NOT_APPLICABLE verdict. On OSS
    builds only INDEXING applies, which is correct since perm sync does not
    exist there.
    """
    get_perm_sync_capabilities = fetch_ee_implementation_or_noop(
        "onyx.connectors.capability_checks",
        "get_applicable_perm_sync_capabilities",
        noop_return_value=set(),
    )
    return {CredentialCapability.INDEXING} | get_perm_sync_capabilities(source)
