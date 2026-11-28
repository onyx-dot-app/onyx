"""Pins the shared credentials-provider construction helper.

``build_db_credentials_provider`` is the single construction site for the
DB-backed provider: ``instantiate_connector`` and source-operation gateways both
route through it, so its output shape is what keeps decrypt-audit, refresh
write-back, and rotation-lock behavior uniform across consumers.
"""

from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import (
    OnyxDBCredentialsProvider,
    build_db_credentials_provider,
)
from shared_configs.contextvars import get_current_tenant_id


def test_helper_builds_the_canonical_db_provider() -> None:
    """
    Verifies the helper yields the DB-backed provider -- the one carrying the
    decrypt-audit and refresh write-back guarantees -- keyed to the credential
    row and the current tenant.
    """

    # Under test.
    provider = build_db_credentials_provider(DocumentSource.SLACK, 42)

    # Postcondition.
    assert isinstance(provider, OnyxDBCredentialsProvider)
    assert provider.is_dynamic() is True
    assert provider.get_provider_key() == "42"
    assert provider.get_tenant_id() == get_current_tenant_id()


def test_rotation_lock_key_is_per_credential() -> None:
    """
    Pins the lock key to the credential alone: connectors of different sources
    can share a family credential, and their renewals must exclude each other.
    """

    # Under test.
    slack_provider = build_db_credentials_provider(DocumentSource.SLACK, 42)
    jira_provider = build_db_credentials_provider(DocumentSource.JIRA, 42)

    # Postcondition.
    assert slack_provider.lock_key == "da_lock:credential_42"
    assert jira_provider.lock_key == slack_provider.lock_key
