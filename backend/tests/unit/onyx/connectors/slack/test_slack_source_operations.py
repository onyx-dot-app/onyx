"""Pins the Slack source-operations gateway: inventory, variants, clients.

The operation table is the living enumeration of every Slack remote interaction;
these tests keep it and the client-construction unification honest.
"""

from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.capabilities import CredentialCapability
from onyx.connectors.slack.source_operations import (
    OnyxSlackWebClient,
    SlackSourceOperations,
    SlackSourceOperationsConfig,
)
from onyx.connectors.source_operations import (
    OperationConsumes,
    get_source_operations_class,
)

_EXPECTED_OPERATIONS = {
    "check_auth",
    "list_channels",
    "list_teams",
    "fetch_team_info",
    "join_channel",
    "fetch_channel_history",
    "fetch_thread_replies",
    "fetch_channel_info",
    "fetch_user_info",
    "list_users",
    "list_channel_members",
    "list_usergroups",
    "list_usergroup_members",
}


def _provider() -> MagicMock:
    provider = MagicMock()
    provider.get_credentials.return_value = {"slack_bot_token": "xoxb-test"}
    provider.get_tenant_id.return_value = "public"
    provider.get_provider_key.return_value = "18"
    return provider


def _gateway(config: dict[str, Any] | None = None) -> SlackSourceOperations:
    return SlackSourceOperations(
        credentials_provider=_provider(), connector_specific_config=config
    )


def test_gateway_registers_for_slack() -> None:
    # Postcondition (registration happened at import).
    assert get_source_operations_class(DocumentSource.SLACK) is SlackSourceOperations
    assert SlackSourceOperations.sdk_modules == ("slack_sdk",)


def test_operation_inventory_is_pinned() -> None:
    """
    Pins the one-method-per-Slack-API-method inventory; a new remote interaction
    must show up here, not in ad-hoc client code.
    """
    # Precondition.
    specs = SlackSourceOperations.operation_specs()

    # Postcondition.
    assert set(specs) == _EXPECTED_OPERATIONS
    # Every operation runs on the bot token alone.
    assert all(spec.consumes == OperationConsumes.CREDENTIAL for spec in specs.values())
    # Only the permanent exemptions remain untested: a side-effecting probe, a
    # gracefully-degrading one, and the dormant group-sync pair. Everything else
    # is exercised by the checks in ``slack/capability_checks.py``.
    assert {name for name, spec in specs.items() if spec.untested} == {
        "join_channel",
        "fetch_team_info",
        "list_usergroups",
        "list_usergroup_members",
    }


def test_permission_class_variants_are_pinned() -> None:
    """Verifies the public/private permission split on channel-scoped reads."""
    # Precondition.
    specs = SlackSourceOperations.operation_specs()

    # Postcondition.
    # Deliberately asserted as strings: call sites use ``SlackChannelVariant``,
    # but these are the wire-level names the spec stores and the coverage
    # harness counts.
    for name in ("list_channels", "fetch_channel_history", "fetch_thread_replies"):
        assert specs[name].variants == ("public", "private")
    # ``conversations.info`` exists to discover the channel's privacy, so it
    # cannot classify itself.
    assert specs["fetch_channel_info"].variants == ()


def test_capability_tags_are_pinned() -> None:
    """
    Verifies which capabilities each operation serves, per real call sites.
    """
    # Precondition.
    specs = SlackSourceOperations.operation_specs()

    # Postcondition.
    # No EXTERNAL_GROUP_SYNC on ``fetch_user_info``: its only group-sync caller
    # is the dormant, unregistered ``group_sync.py`` path.
    assert specs["fetch_user_info"].capabilities == {
        CredentialCapability.INDEXING,
        CredentialCapability.DOC_PERMISSION_SYNC,
    }
    assert specs["list_channel_members"].capabilities == {
        CredentialCapability.DOC_PERMISSION_SYNC
    }
    assert specs["list_usergroups"].capabilities == {
        CredentialCapability.EXTERNAL_GROUP_SYNC
    }


def test_variant_enforcement_fires_before_any_client_exists() -> None:
    """
    Verifies a variant-bearing operation rejects unclassified calls at the
    wrapper, before credential decrypt or client construction.
    """
    # Precondition.
    provider = _provider()
    gateway = SlackSourceOperations(credentials_provider=provider)

    # Under test and postcondition.
    # ``Any``-cast to exercise at runtime the call shape ty rejects statically.
    with pytest.raises(TypeError, match="declares variants"):
        cast(Any, gateway).list_channels(channel_types=["public_channel"])
    provider.get_credentials.assert_not_called()


def test_coordinated_client_uses_the_connector_key_forms() -> None:
    """
    Pins the redis key forms of the unified client: EE perm-sync used to build
    clients under bare-provider-key delay keys that never coordinated with
    indexing; every consumer now shares these.
    """
    # Under test.
    client = _gateway()._client()

    # Postcondition.
    assert isinstance(client, OnyxSlackWebClient)
    assert client._delay_key == "connector:slack:credential_18:delay"
    assert client._delay_lock == "connector:slack:credential_18:delay_lock"


def test_use_redis_false_builds_a_bare_client() -> None:
    """Verifies the dev/test escape hatch skips redis coordination."""
    # Under test.
    client = _gateway({"use_redis": False})._client()

    # Postcondition.
    assert not isinstance(client, OnyxSlackWebClient)


def test_gateway_config_consumes_its_slice_of_the_connector_config() -> None:
    """
    Verifies the raw connector config validates into the typed gateway config:
    connector-only keys are ignored and coordination defaults to on.
    """
    # Under test.
    client = _gateway({"use_redis": False, "channels": ["general"]})._client()

    # Postcondition.
    assert not isinstance(client, OnyxSlackWebClient)
    assert SlackSourceOperationsConfig().use_redis is True


def test_clients_are_memoized_and_fast_client_is_separate() -> None:
    """Verifies one coordinated client and one fast client per gateway."""
    # Precondition.
    gateway = _gateway({"use_redis": False})

    # Under test.
    client = gateway._client()
    fast = gateway._fast_client()

    # Postcondition.
    assert gateway._client() is client
    assert gateway._fast_client() is fast
    assert fast is not client
    assert fast.timeout == 1


def test_check_auth_parses_granted_scopes_from_the_response_header() -> None:
    """
    Verifies scope introspection: ``granted_scopes`` comes from the
    ``X-OAuth-Scopes`` response header (case-insensitive, list-tolerant), not
    the payload.
    """
    # Precondition.
    gateway = _gateway()
    client = MagicMock()
    client.auth_test.return_value = MagicMock(
        data={"ok": True, "url": "https://onyx.slack.com"},
        headers={"X-OAuth-Scopes": ["channels:read, channels:join"]},
    )
    gateway._cached_client = client

    # Under test.
    response = gateway.check_auth()

    # Postcondition.
    assert response.ok is True
    assert response.granted_scopes == ["channels:read", "channels:join"]


def test_check_auth_scopes_are_none_when_the_header_is_absent() -> None:
    """Verifies the absent-header case stays distinguishable from no scopes."""
    # Precondition.
    gateway = _gateway()
    client = MagicMock()
    client.auth_test.return_value = MagicMock(data={"ok": True}, headers={})
    gateway._cached_client = client

    # Under test and postcondition.
    assert gateway.check_auth().granted_scopes is None
