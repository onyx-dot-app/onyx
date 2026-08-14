"""Which perm-sync capabilities exist per source.

Kept apart from the EE check dispatch (``capability_checks``) so applicability
resolution never depends on per-connector check modules: a broken or heavy
check import must not affect callers that only need applicability (the
blocking-validation recorder). ``sync_params`` is the truth source for what
syncs exist and is already part of the EE production import graph.
"""

from ee.onyx.external_permissions.sync_params import (
    source_requires_doc_sync,
    source_requires_external_group_sync,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.capabilities import CredentialCapability


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
