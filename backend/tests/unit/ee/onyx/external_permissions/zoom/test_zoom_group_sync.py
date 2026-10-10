"""The group sync fills the "everyone at <domain>" groups the resolver names
on a recording shared under a domain sign-in rule."""

from typing import Any, cast
from unittest.mock import MagicMock, call, patch

import pytest

from ee.onyx.configs.app_configs import ZOOM_PERMISSION_GROUP_SYNC_FREQUENCY
from ee.onyx.external_permissions.sync_params import (
    get_source_perm_sync_config,
    source_requires_external_group_sync,
)
from ee.onyx.external_permissions.zoom.group_sync import (
    domain_groups,
    zoom_group_sync,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.zoom.connector import ZoomConnector
from onyx.connectors.zoom.models import ZoomRecordingAuthenticationRule, ZoomUserPage
from onyx.connectors.zoom.recordings.models import ZoomListingIncomplete
from onyx.db.models import ConnectorCredentialPair
from tests.unit.onyx.connectors.zoom.helpers import mock_zoom_client
from tests.unit.onyx.connectors.zoom.zoom_api_shapes import (
    domain_rule,
    recording_authentication_settings,
    user,
)


def _page(
    *emails: str,
    next_page_token: str | None = None,
    total_records: int | None = None,
) -> ZoomUserPage:
    """A page Zoom counted; the count is the page's own size unless given."""
    return ZoomUserPage(
        users=[user(email=email) for email in emails],
        next_page_token=next_page_token,
        total_records=len(emails) if total_records is None else total_records,
    )


def _client(
    *pages: ZoomUserPage,
    rules: list[ZoomRecordingAuthenticationRule] | None = None,
) -> MagicMock:
    client = mock_zoom_client()
    client.list_users.side_effect = list(pages)
    client.get_recording_authentication_rules.return_value = (
        recording_authentication_settings(*(rules or []))
    )
    return client


def _groups(client: MagicMock) -> dict[str, list[str]]:
    return {group.id: group.user_emails for group in domain_groups(client)}


def test_users_are_grouped_by_email_domain() -> None:
    client = _client(_page("Ann@Example.com", "bob@example.com", "cy@partner.com"))

    # Bare ids: the source prefix is added when the groups are stored, which
    # is how they meet the ids the resolver writes on a document.
    assert _groups(client) == {
        "domain:example.com": ["ann@example.com", "bob@example.com"],
        "domain:partner.com": ["cy@partner.com"],
    }


def test_every_page_of_the_listing_is_read() -> None:
    client = _client(
        _page("ann@example.com", next_page_token="p2", total_records=2),
        _page("bob@example.com", total_records=2),
    )

    assert _groups(client) == {
        "domain:example.com": ["ann@example.com", "bob@example.com"]
    }
    assert client.list_users.call_args_list == [
        call(page_token=None),
        call(page_token="p2"),
    ]


@pytest.mark.parametrize(
    "page, reason",
    [
        (_page("ann@example.com", total_records=5), "1 of the 5 users"),
        (ZoomUserPage(users=[user()]), "no total_records"),
    ],
    ids=["short", "uncounted"],
)
def test_a_listing_that_cannot_be_checked_fails_the_sync(
    page: ZoomUserPage, reason: str
) -> None:
    client = _client(page)

    with pytest.raises(ZoomListingIncomplete, match=reason):
        list(domain_groups(client))


def test_a_user_zoom_returns_no_email_for_is_left_out() -> None:
    client = _client(_page("ann@example.com", " "))

    assert _groups(client) == {"domain:example.com": ["ann@example.com"]}


def test_a_wildcard_rule_gets_a_group_of_the_subdomains_it_matches() -> None:
    client = _client(
        _page("eu@eu.example.com", "hq@example.com", "p@partner.com"),
        rules=[domain_rule(domains="*.example.com, partner.com")],
    )

    assert _groups(client) == {
        "domain:eu.example.com": ["eu@eu.example.com"],
        "domain:example.com": ["hq@example.com"],
        "domain:partner.com": ["p@partner.com"],
        "domain:*.example.com": ["eu@eu.example.com"],
    }
    # The catalogue is read through a user the roster listed, not by listing again.
    client.list_users.assert_called_once()


def test_a_wildcard_nobody_matches_gets_no_group() -> None:
    client = _client(
        _page("hq@example.com"), rules=[domain_rule(domains="*.other.com")]
    )

    assert _groups(client) == {"domain:example.com": ["hq@example.com"]}


def test_the_sync_reads_the_roster_through_the_connectors_credentials() -> None:
    fake = _client(_page("ann@example.com"))
    cc_pair = MagicMock(spec=ConnectorCredentialPair)
    cc_pair.connector.connector_specific_config = {"host_emails": ["ann@example.com"]}
    cc_pair.credential.credential_json.get_value.return_value = {
        "zoom_account_id": "acct"
    }

    def _fake_load(self: ZoomConnector, credentials: dict[str, Any]) -> None:
        assert credentials == {"zoom_account_id": "acct"}
        self.client = fake

    with patch.object(ZoomConnector, "load_credentials", _fake_load):
        groups = list(zoom_group_sync("tenant", cast(ConnectorCredentialPair, cc_pair)))

    assert [group.id for group in groups] == ["domain:example.com"]


def test_zoom_is_registered_for_group_sync() -> None:
    assert source_requires_external_group_sync(DocumentSource.ZOOM)
    config = get_source_perm_sync_config(DocumentSource.ZOOM)
    assert config is not None and config.group_sync_config is not None
    assert (
        config.group_sync_config.group_sync_frequency
        == ZOOM_PERMISSION_GROUP_SYNC_FREQUENCY
    )
