"""One test per row of the Link access table, with the checkbox on and off,
plus the traps the order of checks exists for. The shapes are what Zoom sent
for a live recording after each choice was set."""

from collections.abc import Callable, Iterable
from unittest.mock import MagicMock

import pytest
import requests
from pydantic import ValidationError

from onyx.connectors.zoom.models import (
    ZoomRecordingAuthenticationRule,
    ZoomRecordingRegistrant,
    ZoomRecordingSettings,
    ZoomUser,
    ZoomUserPage,
)
from onyx.connectors.zoom.recordings.recording_access import (
    RuleGrant,
    ZoomAccessListUnavailable,
    load_rule_grants,
    look_up_owner_email,
    resolve_recording_access,
)
from tests.unit.onyx.connectors.zoom.helpers import http_error, mock_zoom_client
from tests.unit.onyx.connectors.zoom.zoom_api_shapes import (
    ACCOUNT_RULE_ID,
    recording_authentication_rule,
    recording_authentication_settings,
    recording_entry,
    recording_registrant,
    recording_settings,
    user,
)

_DOMAIN_RULE_ID = "KtK6lLjFQp24UqYxdYQQuA"
_ANY_ZOOM_USER_RULE_ID = "enforce_login_GB7nutLVSz-Aoi3nrsxZrw"
_EVERYONE = RuleGrant(public=True, domains=frozenset())
_OWNER_ONLY = RuleGrant(public=False, domains=frozenset())
_DOMAINS = RuleGrant(public=False, domains=frozenset({"onyx.app", "partner.com"}))
_RULE_GRANTS = {
    ACCOUNT_RULE_ID: _EVERYONE,
    _ANY_ZOOM_USER_RULE_ID: _EVERYONE,
    _DOMAIN_RULE_ID: _DOMAINS,
}
_OWNER = "owner@example.com"

PRIVATE_TO_ME = ZoomRecordingSettings(share_recording="none")
ONLY_PEOPLE_WITH_ACCESS = recording_settings(
    authentication_option="specialEmail", authentication_name="Only people with access"
)
ANYONE_WITH_THE_LINK = recording_settings(
    recording_authentication=False, authentication_option="", authentication_name=""
)
ANYONE_IN_MY_ACCOUNT = recording_settings()
ANYONE_IN_DOMAIN_RULE = recording_settings(authentication_option=_DOMAIN_RULE_ID)
ANYONE_SIGNED_IN_TO_ZOOM = recording_settings(
    authentication_option=_ANY_ZOOM_USER_RULE_ID
)

# (settings, public with the box on, groups with the box on)
_LINK_ACCESS_ROWS = [
    (PRIVATE_TO_ME, False, set()),
    (ONLY_PEOPLE_WITH_ACCESS, False, set()),
    (ANYONE_IN_DOMAIN_RULE, False, {"zoom_domain:onyx.app", "zoom_domain:partner.com"}),
    (ANYONE_IN_MY_ACCOUNT, True, set()),
    (ANYONE_SIGNED_IN_TO_ZOOM, True, set()),
    (ANYONE_WITH_THE_LINK, True, set()),
]
_LINK_ACCESS_IDS = [
    "private-to-me",
    "only-people-with-access",
    "domain-rule",
    "my-account",
    "any-zoom-user",
    "anyone-with-the-link",
]


def _client(
    settings: ZoomRecordingSettings,
    registrants: Iterable[ZoomRecordingRegistrant] = (),
) -> MagicMock:
    client = mock_zoom_client()
    client.get_recording_settings.return_value = settings
    client.list_recording_registrants.return_value = list(registrants)
    return client


def _resolve(
    client: MagicMock,
    *,
    box_on: bool = True,
    rule_grant: Callable[[str], RuleGrant | None] = _RULE_GRANTS.get,
    owner: str | None = _OWNER,
    add_prefix: bool = True,
):
    return resolve_recording_access(
        client,
        recording_entry(uuid="rec-1", host_id="owner-1"),
        treat_link_access_as_public=box_on,
        rule_grant=rule_grant,
        owner_email=owner,
        add_prefix=add_prefix,
    )


class TestTheLinkAccessTable:
    @pytest.mark.parametrize(
        ("settings", "public", "groups"), _LINK_ACCESS_ROWS, ids=_LINK_ACCESS_IDS
    )
    def test_with_the_box_on(
        self, settings: ZoomRecordingSettings, public: bool, groups: set[str]
    ) -> None:
        access = _resolve(_client(settings))

        assert access.external_user_emails == {_OWNER}
        assert access.is_public is public
        assert access.external_user_group_ids == groups

    def test_the_doc_sync_gets_bare_group_ids(self) -> None:
        # upsert_document_external_perms adds the source prefix itself.
        access = _resolve(_client(ANYONE_IN_DOMAIN_RULE), add_prefix=False)

        assert access.external_user_group_ids == {
            "domain:onyx.app",
            "domain:partner.com",
        }

    @pytest.mark.parametrize(
        "settings", [row[0] for row in _LINK_ACCESS_ROWS], ids=_LINK_ACCESS_IDS
    )
    def test_with_the_box_off_every_choice_is_owner_only(
        self, settings: ZoomRecordingSettings
    ) -> None:
        access = _resolve(_client(settings), box_on=False)

        assert access.external_user_emails == {_OWNER}
        assert access.is_public is False
        assert access.external_user_group_ids == set()


class TestTheTraps:
    def test_only_people_with_access_is_decided_before_the_catalogue(self) -> None:
        # Live, its payload still says share_recording publicly and its id is
        # not in the catalogue; a catalogue that had it must not win either.
        rule_grant = (_RULE_GRANTS | {"specialEmail": _EVERYONE}).get

        access = _resolve(_client(ONLY_PEOPLE_WITH_ACCESS), rule_grant=rule_grant)

        assert access.external_user_emails == {_OWNER}
        assert access.is_public is False

    def test_sign_in_required_under_no_named_rule_grants_only_the_owner(
        self,
    ) -> None:
        # Not seen live. Whatever rule Zoom applies then, the connector cannot read it.
        settings = recording_settings(
            recording_authentication=True, authentication_option=""
        )

        access = _resolve(_client(settings))

        assert access.external_user_emails == {_OWNER}
        assert access.is_public is False
        assert access.external_user_group_ids == set()

    def test_a_rule_missing_from_the_catalogue_grants_only_the_owner(self) -> None:
        settings = recording_settings(authentication_option="deleted-rule")

        access = _resolve(_client(settings))

        assert access.external_user_emails == {_OWNER}
        assert access.is_public is False
        assert access.external_user_group_ids == set()

    def test_share_settings_zoom_does_not_document_grant_only_the_owner(
        self,
    ) -> None:
        client = _client(ANYONE_IN_MY_ACCOUNT)
        client.get_recording_settings.side_effect = ValidationError.from_exception_data(
            "ZoomRecordingSettings", []
        )

        access = _resolve(client)

        assert access.external_user_emails == {_OWNER}
        assert access.is_public is False


class TestRegisteredViewers:
    @pytest.mark.parametrize("box_on", [True, False], ids=["box-on", "box-off"])
    def test_approved_registrants_are_added_whatever_the_box_says(
        self, box_on: bool
    ) -> None:
        client = _client(
            recording_settings(on_demand=True),
            registrants=[
                recording_registrant(email="Viewer@Example.com", status="approved"),
                # Zoom was asked for approved only; the answer is checked anyway.
                recording_registrant(email="pending@example.com", status="pending"),
                recording_registrant(email="  ", status="approved"),
            ],
        )

        access = _resolve(client, box_on=box_on)

        assert access.external_user_emails == {_OWNER, "viewer@example.com"}
        client.list_recording_registrants.assert_called_once_with(
            "rec-1", status="approved"
        )

    @pytest.mark.parametrize(
        "settings",
        [
            ZoomRecordingSettings(share_recording="none", on_demand=True),
            ANYONE_IN_MY_ACCOUNT,
        ],
        ids=["private-to-me-with-registration", "registration-off"],
    )
    def test_nobody_is_asked_for_otherwise(
        self, settings: ZoomRecordingSettings
    ) -> None:
        client = _client(settings)

        _resolve(client)

        client.list_recording_registrants.assert_not_called()


class TestAMissingOwner:
    def test_fails_a_recording_nobody_else_may_watch(self) -> None:
        with pytest.raises(ZoomAccessListUnavailable, match="owner-1"):
            _resolve(_client(PRIVATE_TO_ME), owner=None)

    def test_does_not_fail_a_public_recording(self) -> None:
        access = _resolve(_client(ANYONE_WITH_THE_LINK), owner=None)

        assert access.is_public is True
        assert access.external_user_emails == set()


class TestLookUpOwnerEmail:
    def _client(self, owner: ZoomUser) -> MagicMock:
        client = mock_zoom_client()
        client.get_user.return_value = owner
        return client

    def test_the_address_is_normalised(self) -> None:
        client = self._client(user(id="owner-1", email="Owner@Example.com"))

        assert look_up_owner_email(client, "owner-1") == "owner@example.com"
        client.get_user.assert_called_once_with("owner-1")

    def test_an_owner_zoom_no_longer_has_is_none(self) -> None:
        client = mock_zoom_client()
        client.get_user.side_effect = http_error(404, 1001)

        assert look_up_owner_email(client, "left-the-company") is None

    def test_an_owner_with_no_email_yet_counts_as_missing(self) -> None:
        client = self._client(user(id="owner-1", email=""))

        assert look_up_owner_email(client, "owner-1") is None

    def test_any_other_answer_reaches_the_caller(self) -> None:
        # A 404 without Zoom's code, such as from a proxy, is not absence.
        client = mock_zoom_client()
        client.get_user.side_effect = http_error(404)

        with pytest.raises(requests.HTTPError):
            look_up_owner_email(client, "owner-1")


class TestLoadRuleGrants:
    def _client(
        self,
        *rules: ZoomRecordingAuthenticationRule,
        users: Iterable[ZoomUser] = (user(id="someone-else"),),
    ) -> MagicMock:
        client = mock_zoom_client()
        listed = list(users)
        client.list_users.return_value = ZoomUserPage(
            users=listed, total_records=len(listed)
        )
        client.get_recording_authentication_rules.return_value = (
            recording_authentication_settings(*rules)
        )
        return client

    @pytest.mark.parametrize(
        ("rule", "grant"),
        [
            (recording_authentication_rule(), _EVERYONE),
            (
                recording_authentication_rule(
                    id=_ANY_ZOOM_USER_RULE_ID, type="enforce_login"
                ),
                _EVERYONE,
            ),
            (
                recording_authentication_rule(
                    id=_DOMAIN_RULE_ID,
                    type="enforce_login_with_domains",
                    domains="Onyx.app, partner.com",
                ),
                _DOMAINS,
            ),
            (
                recording_authentication_rule(
                    id=_DOMAIN_RULE_ID, type="enforce_login_with_domains", domains=" "
                ),
                _OWNER_ONLY,
            ),
            (recording_authentication_rule(type="biometric"), _OWNER_ONLY),
        ],
        ids=[
            "my-account",
            "any-zoom-user",
            "domain-rule",
            "domain-rule-without-domains",
            "type-zoom-adds-later",
        ],
    )
    def test_each_rule_type_maps_to_what_it_grants(
        self, rule: ZoomRecordingAuthenticationRule, grant: RuleGrant
    ) -> None:
        assert load_rule_grants(self._client(rule)) == {rule.id: grant}

    def test_the_catalogue_is_asked_through_a_user_the_account_lists(self) -> None:
        client = self._client()

        load_rule_grants(client)

        client.list_users.assert_called_once_with()
        client.get_recording_authentication_rules.assert_called_once_with(
            "someone-else"
        )

    def test_an_account_without_users_has_no_rules(self) -> None:
        client = self._client(users=())

        assert load_rule_grants(client) == {}
        client.get_recording_authentication_rules.assert_not_called()
