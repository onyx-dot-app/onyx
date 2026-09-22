"""One test per row of the Link access table, with the checkbox on and off,
plus the traps the order of checks exists for. The shapes are what Zoom sent
on 2026-09-22, read live after setting each choice."""

from unittest.mock import MagicMock

import pytest
import requests
from pydantic import ValidationError

from onyx.connectors.zoom.models import ZoomRecordingSettings
from onyx.connectors.zoom.recordings.recording_access import (
    ZoomAccessContext,
    ZoomAccessListUnavailable,
    resolve_recording_access,
)
from tests.unit.onyx.connectors.zoom.helpers import http_error, with_recording_access
from tests.unit.onyx.connectors.zoom.zoom_api_shapes import (
    ACCOUNT_RULE_ID,
    recording_authentication_rule,
    recording_entry,
    recording_registrant,
    recording_settings,
    user,
)

_DOMAIN_RULE_ID = "KtK6lLjFQp24UqYxdYQQuA"
_ANY_ZOOM_USER_RULE_ID = "enforce_login_GB7nutLVSz-Aoi3nrsxZrw"
_RULES = [
    recording_authentication_rule(),
    recording_authentication_rule(
        id=_DOMAIN_RULE_ID,
        type="enforce_login_with_domains",
        domains="Onyx.app, partner.com",
    ),
    recording_authentication_rule(id=_ANY_ZOOM_USER_RULE_ID, type="enforce_login"),
]

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


def _client(settings: ZoomRecordingSettings) -> MagicMock:
    return with_recording_access(settings=settings, rules=_RULES)


def _resolve(client: MagicMock, *, box_on: bool = True, host_id: str = "owner-1"):
    context = ZoomAccessContext(client, treat_link_access_as_public=box_on)
    return resolve_recording_access(
        context, recording_entry(uuid="rec-1", host_id=host_id)
    )


class TestTheLinkAccessTable:
    @pytest.mark.parametrize(
        ("settings", "public", "groups"), _LINK_ACCESS_ROWS, ids=_LINK_ACCESS_IDS
    )
    def test_with_the_box_on(
        self, settings: ZoomRecordingSettings, public: bool, groups: set[str]
    ) -> None:
        access = _resolve(_client(settings))

        assert access.external_user_emails == {"owner@example.com"}
        assert access.is_public is public
        assert access.external_user_group_ids == groups

    @pytest.mark.parametrize(
        "settings", [row[0] for row in _LINK_ACCESS_ROWS], ids=_LINK_ACCESS_IDS
    )
    def test_with_the_box_off_every_choice_is_owner_only(
        self, settings: ZoomRecordingSettings
    ) -> None:
        access = _resolve(_client(settings), box_on=False)

        assert access.external_user_emails == {"owner@example.com"}
        assert access.is_public is False
        assert access.external_user_group_ids == set()


class TestTheTraps:
    def test_only_people_with_access_never_consults_the_catalogue(self) -> None:
        # Its rule id is not in the catalogue, and the live payload still says
        # share_recording publicly, so it has to be decided before either.
        client = _client(ONLY_PEOPLE_WITH_ACCESS)

        _resolve(client)

        client.get_recording_authentication_rules.assert_not_called()

    @pytest.mark.parametrize(
        ("rule_id", "rules"),
        [
            ("deleted-rule", [recording_authentication_rule()]),
            (ACCOUNT_RULE_ID, [recording_authentication_rule(type="biometric")]),
            (
                _DOMAIN_RULE_ID,
                [
                    recording_authentication_rule(
                        id=_DOMAIN_RULE_ID,
                        type="enforce_login_with_domains",
                        domains=" ",
                    )
                ],
            ),
        ],
        ids=["rule-missing", "type-zoom-adds-later", "domain-rule-without-domains"],
    )
    def test_a_rule_the_connector_cannot_read_grants_only_the_owner(
        self, rule_id: str, rules: list
    ) -> None:
        client = with_recording_access(
            settings=recording_settings(authentication_option=rule_id), rules=rules
        )

        access = _resolve(client)

        assert access.external_user_emails == {"owner@example.com"}
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

        assert access.external_user_emails == {"owner@example.com"}
        assert access.is_public is False


class TestRegisteredViewers:
    @pytest.mark.parametrize("box_on", [True, False], ids=["box-on", "box-off"])
    def test_approved_registrants_are_added_whatever_the_box_says(
        self, box_on: bool
    ) -> None:
        client = with_recording_access(
            settings=recording_settings(on_demand=True),
            rules=_RULES,
            registrants=[
                recording_registrant(email="Viewer@Example.com", status="approved"),
                # Zoom was asked for approved only; the answer is checked anyway.
                recording_registrant(email="pending@example.com", status="pending"),
                recording_registrant(email="  ", status="approved"),
            ],
        )

        access = _resolve(client, box_on=box_on)

        assert access.external_user_emails == {
            "owner@example.com",
            "viewer@example.com",
        }
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
        # Nobody can reach the registration page of a private recording, and an
        # owner who went private wants everyone out.
        client = _client(settings)

        _resolve(client)

        client.list_recording_registrants.assert_not_called()


class TestTheOwner:
    def test_an_owner_zoom_no_longer_has_fails_the_document(self) -> None:
        # Indexing it would bury a transcript nobody can reach.
        client = _client(PRIVATE_TO_ME)
        client.get_user.side_effect = http_error(404, 1001)

        with pytest.raises(ZoomAccessListUnavailable, match="left-the-company"):
            _resolve(client, host_id="left-the-company")

    def test_an_owner_with_no_email_yet_counts_as_missing(self) -> None:
        # Zoom keeps the address blank until an invitation is accepted.
        client = with_recording_access(
            settings=PRIVATE_TO_ME, owner=user(id="owner-1", email="")
        )

        with pytest.raises(ZoomAccessListUnavailable):
            _resolve(client)

    def test_a_public_recording_survives_a_missing_owner(self) -> None:
        client = _client(ANYONE_WITH_THE_LINK)
        client.get_user.side_effect = http_error(404, 1001)

        access = _resolve(client, host_id="left-the-company")

        assert access.is_public is True
        assert access.external_user_emails == set()

    def test_any_other_answer_about_the_owner_reaches_the_caller(self) -> None:
        # A 404 without Zoom's code, such as from a proxy, is not absence.
        client = _client(PRIVATE_TO_ME)
        client.get_user.side_effect = http_error(404)

        with pytest.raises(requests.HTTPError):
            _resolve(client)

    def test_owners_and_rules_are_asked_for_once_per_run(self) -> None:
        client = _client(ANYONE_IN_DOMAIN_RULE)
        context = ZoomAccessContext(client, treat_link_access_as_public=True)

        for uuid in ("rec-1", "rec-2", "rec-3"):
            resolve_recording_access(
                context, recording_entry(uuid=uuid, host_id="owner-1")
            )

        client.get_user.assert_called_once_with("owner-1")
        client.get_recording_authentication_rules.assert_called_once_with("owner-1")
