"""Which capabilities exist per source on this build.

Kept apart from the check registry so hot-path modules (the blocking
validation recorder) can resolve applicability without importing the
registry, which eagerly imports every migrated connector's check module.
"""

from onyx.configs.constants import DocumentSource
from onyx.connectors.capabilities import CredentialCapability
from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop


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
