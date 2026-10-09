"""Unit tests for lazy resolution of Slack workspace metadata.

Workspace URL and Enterprise Grid topology are resolved when an indexing entry
point primes them, not when credentials are set. The coordinated client
serializes on a Redis lock shared with running indexing jobs, so resolving
eagerly lets a rate-limited indexing job block connector creation for the length
of its backoff. These tests pin the guarantee that the validation path never
touches that client, and that the exposed properties stay side-effect free.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.slack.connector import SlackConnector
from onyx.connectors.slack.source_operations import SlackApiError

_AUTH_NON_GRID = {"url": "https://workspace.slack.com"}
_AUTH_GRID = {"url": "https://workspace.slack.com", "enterprise_id": "E1"}


def _slack_response(data: dict[str, Any]) -> MagicMock:
    """
    Mimics a SlackResponse: ``validate()``, ``.data``, and mapping ``get``.
    """
    response = MagicMock()
    response.data = data
    response.get.side_effect = data.get
    return response


def _set_credentials(connector: SlackConnector) -> tuple[MagicMock, MagicMock]:
    """Attaches mocked clients, returning ``(client, fast_client)``.

    The gateway builds its clients lazily and memoizes them, so injecting mocks
    into the memoization slots makes every operation run against them.
    """
    client = MagicMock()
    fast_client = MagicMock()

    provider = MagicMock()
    provider.get_credentials.return_value = {"slack_bot_token": "xoxb-test"}
    provider.get_tenant_id.return_value = "public"
    provider.get_provider_key.return_value = "18"

    connector.set_credentials_provider(provider)
    assert connector.slack_client is not None
    connector.slack_client._cached_client = client
    connector.slack_client._cached_fast_client = fast_client

    return client, fast_client


def _connector() -> tuple[SlackConnector, MagicMock, MagicMock]:
    connector = SlackConnector(channels=None, use_redis=False)
    client, fast_client = _set_credentials(connector)
    return connector, client, fast_client


class TestLazyResolution:
    def test_setting_credentials_does_not_call_auth_test(self) -> None:
        _, client, _ = _connector()
        client.auth_test.assert_not_called()

    def test_setting_credentials_does_not_read_the_credential(self) -> None:
        """Client construction is lazy, so the decrypt happens at first call."""
        connector = SlackConnector(channels=None, use_redis=False)
        provider = MagicMock()
        provider.get_tenant_id.return_value = "public"
        provider.get_provider_key.return_value = "18"

        connector.set_credentials_provider(provider)

        provider.get_credentials.assert_not_called()

    def test_validation_never_touches_the_coordinated_client(self) -> None:
        connector, client, fast_client = _connector()
        fast_client.auth_test.return_value = _slack_response({"ok": True})
        fast_client.conversations_list.return_value = _slack_response(
            {"ok": True, "channels": []}
        )

        connector.validate_connector_settings()

        client.auth_test.assert_not_called()
        fast_client.auth_test.assert_called_once()

    def test_properties_do_no_work_until_primed(self) -> None:
        connector, client, _ = _connector()
        client.auth_test.return_value = _slack_response(_AUTH_NON_GRID)

        assert connector.workspace_url is None
        assert connector.grid_team_ids is None
        client.auth_test.assert_not_called()

    def test_priming_resolves_and_result_is_cached(self) -> None:
        connector, client, _ = _connector()
        client.auth_test.return_value = _slack_response(_AUTH_NON_GRID)

        connector._ensure_workspace_metadata()
        connector._ensure_workspace_metadata()

        assert connector.workspace_url == "https://workspace.slack.com"
        client.auth_test.assert_called_once()

    def test_failed_resolution_raises_and_caches_nothing(self) -> None:
        """Fails closed: an empty Grid mapping would widen public-channel ACLs."""
        connector, client, _ = _connector()
        client.auth_test.side_effect = SlackApiError("boom", MagicMock())

        with pytest.raises(SlackApiError):
            connector._ensure_workspace_metadata()

        assert connector._workspace_metadata is None

        client.auth_test.side_effect = None
        client.auth_test.return_value = _slack_response(_AUTH_NON_GRID)
        connector._ensure_workspace_metadata()
        assert connector.workspace_url == "https://workspace.slack.com"

    def test_grid_team_enumeration_failure_raises(self) -> None:
        connector, client, _ = _connector()
        client.auth_test.return_value = _slack_response(_AUTH_GRID)

        with patch(
            "onyx.connectors.slack.connector.list_grid_team_ids",
            side_effect=SlackApiError("missing_scope", MagicMock()),
        ):
            with pytest.raises(SlackApiError):
                connector._ensure_workspace_metadata()

        assert connector._workspace_metadata is None

    def test_grid_user_email_failure_raises(self) -> None:
        connector, client, _ = _connector()
        client.auth_test.return_value = _slack_response(_AUTH_GRID)

        with (
            patch(
                "onyx.connectors.slack.connector.list_grid_team_ids",
                return_value=["T1"],
            ),
            patch(
                "onyx.connectors.slack.connector.fetch_team_url",
                return_value="https://t1.slack.com",
            ),
            patch(
                "onyx.connectors.slack.connector.fetch_team_user_emails",
                side_effect=SlackApiError("missing_scope", MagicMock()),
            ),
        ):
            with pytest.raises(SlackApiError):
                connector._ensure_workspace_metadata()

        assert connector._workspace_metadata is None

    def test_new_credentials_invalidate_cached_metadata(self) -> None:
        connector, client, _ = _connector()
        client.auth_test.return_value = _slack_response(_AUTH_NON_GRID)
        connector._ensure_workspace_metadata()
        assert connector.workspace_url == "https://workspace.slack.com"

        new_client, _ = _set_credentials(connector)
        new_client.auth_test.return_value = _slack_response(
            {"url": "https://other.slack.com"}
        )
        connector._ensure_workspace_metadata()

        assert connector.workspace_url == "https://other.slack.com"
        new_client.auth_test.assert_called_once()

    def test_unconfigured_connector_reads_defaults_without_raising(self) -> None:
        connector = SlackConnector(channels=None, use_redis=False)

        connector._ensure_workspace_metadata()

        assert connector.workspace_url is None
        assert connector.grid_team_ids is None


class TestLazyGridResolution:
    def test_grid_topology_resolved_when_primed(self) -> None:
        connector, client, _ = _connector()
        client.auth_test.return_value = _slack_response(_AUTH_GRID)

        with (
            patch(
                "onyx.connectors.slack.connector.list_grid_team_ids",
                return_value=["T1"],
            ) as list_teams,
            patch(
                "onyx.connectors.slack.connector.fetch_team_url",
                return_value="https://t1.slack.com",
            ),
            patch(
                "onyx.connectors.slack.connector.fetch_team_user_emails",
                return_value={"T1": {"a@example.com"}},
            ),
        ):
            list_teams.assert_not_called()
            connector._ensure_workspace_metadata()

        assert connector.grid_team_ids == ["T1"]
        assert connector.grid_team_id_to_url == {"T1": "https://t1.slack.com"}
        assert connector.grid_team_id_to_user_emails == {"T1": {"a@example.com"}}
        list_teams.assert_called_once()
        client.auth_test.assert_called_once()

    def test_validation_probes_users_scope_on_grid(self) -> None:
        connector, _, fast_client = _connector()
        fast_client.auth_test.return_value = _slack_response(
            {"ok": True, "enterprise_id": "E1"}
        )
        fast_client.conversations_list.return_value = _slack_response(
            {"ok": True, "channels": []}
        )
        fast_client.auth_teams_list.return_value = _slack_response(
            {"teams": [{"id": "T1"}]}
        )
        fast_client.users_list.return_value = _slack_response({"members": []})

        connector.validate_connector_settings()

        # The gateway paginator supplies the cursor argument.
        fast_client.users_list.assert_called_once_with(
            cursor=None, limit=1, team_id="T1"
        )

    def test_validation_surfaces_missing_users_scope(self) -> None:
        connector, _, fast_client = _connector()
        fast_client.auth_test.return_value = _slack_response(
            {"ok": True, "enterprise_id": "E1"}
        )
        fast_client.conversations_list.return_value = _slack_response(
            {"ok": True, "channels": []}
        )
        fast_client.auth_teams_list.return_value = _slack_response(
            {"teams": [{"id": "T1"}]}
        )
        error_response = MagicMock()
        error_response.get.side_effect = lambda key, default=None: {
            "error": "missing_scope",
            "needed": "users:read.email",
        }.get(key, default)
        fast_client.users_list.side_effect = SlackApiError("boom", error_response)

        with pytest.raises(InsufficientPermissionsError, match="users:read.email"):
            connector.validate_connector_settings()

    def test_validation_skips_users_probe_off_grid(self) -> None:
        connector, _, fast_client = _connector()
        fast_client.auth_test.return_value = _slack_response({"ok": True})
        fast_client.conversations_list.return_value = _slack_response(
            {"ok": True, "channels": []}
        )

        connector.validate_connector_settings()

        fast_client.auth_teams_list.assert_not_called()
        fast_client.users_list.assert_not_called()

    def test_non_grid_workspace_skips_team_enumeration(self) -> None:
        connector, client, _ = _connector()
        client.auth_test.return_value = _slack_response(_AUTH_NON_GRID)

        with patch("onyx.connectors.slack.connector.list_grid_team_ids") as list_teams:
            connector._ensure_workspace_metadata()

        assert connector.grid_team_ids is None
        list_teams.assert_not_called()
