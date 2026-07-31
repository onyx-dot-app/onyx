"""EE implementation of perm-sync capability checks.

Fetched by ``onyx.connectors.capability_checks.registry`` via
``fetch_ee_implementation_or_noop``. Only the dispatch lives here; the check
implementations stay in the OSS connector modules, mirroring the
``perm_sync_valid.py`` pattern.
"""

from ee.onyx.external_permissions.sync_params import (
    source_requires_doc_sync,
    source_requires_external_group_sync,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CredentialCapability,
)

# Named perm-sync checks per source. Empty at framework stage: per-connector
# work registers named checks here.
_DOC_PERMISSION_SYNC_CHECKS_BY_SOURCE: dict[DocumentSource, list[CapabilityCheck]] = {}

_EXTERNAL_GROUP_SYNC_CHECKS_BY_SOURCE: dict[DocumentSource, list[CapabilityCheck]] = {}


class _PermSyncFallbackCheck(CapabilityCheck):
    """Baseline check for a perm-sync capability with no named checks.

    Wraps the legacy ``validate_perm_sync`` blob, which covers doc sync and
    group sync together; the checks for both capabilities are therefore two
    instances of this class sharing one check_id, and the runner executes the
    probe once per run and mirrors the outcome onto each.
    """

    def __init__(
        self, source: DocumentSource, capability: CredentialCapability
    ) -> None:
        super().__init__(
            capability=capability,
            check_id=f"{source.value}_perm_sync",
            display_name="Permission sync validation",
            is_fallback=True,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        assert context.connector is not None, "The runner guarantees an instance."
        context.connector.validate_perm_sync()


def get_applicable_perm_sync_capabilities(
    source: DocumentSource,
) -> set[CredentialCapability]:
    """Returns which perm-sync capabilities exist for this source."""
    applicable: set[CredentialCapability] = set()
    if source_requires_doc_sync(source):
        applicable.add(CredentialCapability.DOC_PERMISSION_SYNC)
    if source_requires_external_group_sync(source):
        applicable.add(CredentialCapability.EXTERNAL_GROUP_SYNC)
    return applicable


def get_perm_sync_capability_checks(source: DocumentSource) -> list[CapabilityCheck]:
    """Returns the perm-sync capability checks for a source.

    Applicable capabilities with no registered named checks get the shared
    ``validate_perm_sync`` fallback so every sync-capable source has day-one
    coverage.
    """
    applicable = get_applicable_perm_sync_capabilities(source)
    registered_by_capability: dict[CredentialCapability, list[CapabilityCheck]] = {
        CredentialCapability.DOC_PERMISSION_SYNC: (
            _DOC_PERMISSION_SYNC_CHECKS_BY_SOURCE.get(source, [])
        ),
        CredentialCapability.EXTERNAL_GROUP_SYNC: (
            _EXTERNAL_GROUP_SYNC_CHECKS_BY_SOURCE.get(source, [])
        ),
    }
    checks: list[CapabilityCheck] = []
    for capability, registered in registered_by_capability.items():
        if registered:
            checks.extend(registered)
        elif capability in applicable:
            checks.append(_PermSyncFallbackCheck(source, capability))
    return checks
