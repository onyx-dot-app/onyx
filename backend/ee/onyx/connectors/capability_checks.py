"""EE implementation of perm-sync capability checks.

Fetched by ``onyx.connectors.capability_checks.registry`` via
``fetch_ee_implementation_or_noop``. Only the dispatch lives here; the check
implementations stay in the OSS connector modules, mirroring the
``perm_sync_valid.py`` pattern.
"""

# Re-exported: applicability lives in its own module so its resolution never
# depends on the per-connector check imports below.
from ee.onyx.connectors.capability_applicability import (
    get_applicable_perm_sync_capabilities as get_applicable_perm_sync_capabilities,
)
from ee.onyx.connectors.perm_sync_valid import source_has_perm_sync_probe
from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CredentialCapability,
)
from onyx.connectors.slack.capability_checks import (
    build_slack_doc_permission_sync_checks,
)
from onyx.connectors.source_operations import get_source_operations_class

# Named perm-sync checks per source. Per-connector work registers named checks
# here.
_DOC_PERMISSION_SYNC_CHECKS_BY_SOURCE: dict[DocumentSource, list[CapabilityCheck]] = {
    DocumentSource.SLACK: build_slack_doc_permission_sync_checks(),
}

# Slack registers nothing here by design: it has no group sync (channel access
# resolves usergroups to individual users, so there is no usergroup-to-document
# mapping).
_EXTERNAL_GROUP_SYNC_CHECKS_BY_SOURCE: dict[DocumentSource, list[CapabilityCheck]] = {}


class _PermSyncFallbackCheck(CapabilityCheck):
    """
    Baseline check for a perm-sync capability where the source registers no
    named checks.

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
        assert context.connector is not None, (
            "The runner guarantees an instance of a connector."
        )
        context.connector.validate_perm_sync()


def get_perm_sync_capability_checks(source: DocumentSource) -> list[CapabilityCheck]:
    """Returns the perm-sync capability checks for a source.

    Applicable capabilities with no registered named checks get the shared
    ``validate_perm_sync`` fallback -- but only for probe-bearing sources,
    derived from that blob's own dispatch table via
    ``source_has_perm_sync_probe``. Sync-capable sources where the blob is a
    no-op get no perm-sync checks at all until named ones are registered; their
    verdict renders as "no checks available yet" rather than a trivial PASSED
    built on a no-op probe.

    Ratchet: named checks require a registered source-operations gateway --
    participation in the checks system is an anti-drift guarantee. Unmigrated
    sources keep the fallback path.
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
    assert (
        not any(registered_by_capability.values())
        or get_source_operations_class(source) is not None
    ), (
        f"{source.value} registers named perm-sync checks but no "
        "source-operations gateway; migrate the connector first."
    )
    checks: list[CapabilityCheck] = []
    for capability, registered in registered_by_capability.items():
        if registered:
            checks.extend(registered)
        elif capability in applicable and source_has_perm_sync_probe(source):
            checks.append(_PermSyncFallbackCheck(source, capability))
    return checks
