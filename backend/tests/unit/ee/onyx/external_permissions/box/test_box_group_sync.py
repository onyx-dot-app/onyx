from typing import cast
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from box_sdk_gen import BoxClient
from box_sdk_gen.schemas.group_full import GroupFull
from box_sdk_gen.schemas.user_mini import UserMini

from ee.onyx.external_permissions.box import group_sync as group_sync_module
from ee.onyx.external_permissions.box.group_sync import box_group_sync
from onyx.connectors.box.connector import box_all_enterprise_users_group_id
from onyx.connectors.box.connector import box_group_id
from onyx.connectors.box.connector import BoxConnector
from onyx.db.models import ConnectorCredentialPair
from tests.unit.onyx.connectors.box.fake_box_client import FakeBoxClient

_ENTERPRISE_ID = "ent42"


def _run_group_sync(fake: FakeBoxClient) -> dict[str, list[str]]:
    """Drive box_group_sync with the enterprise client stubbed to `fake`,
    returning {group_id: sorted member emails}."""
    cc_pair = MagicMock(spec=ConnectorCredentialPair)
    cc_pair.connector = MagicMock()
    cc_pair.connector.connector_specific_config = {}
    cc_pair.credential = MagicMock()
    cc_pair.credential.credential_json = MagicMock()
    cc_pair.credential.credential_json.get_value.return_value = {
        "box_enterprise_id": _ENTERPRISE_ID
    }

    def _fake_load(self: BoxConnector, _creds: dict[str, str]) -> None:
        self._enterprise_client = cast(BoxClient, fake)
        return None

    with patch.object(BoxConnector, "load_credentials", _fake_load):
        groups = list(box_group_sync("tenant", cast(ConnectorCredentialPair, cc_pair)))
    return {g.id: sorted(g.user_emails) for g in groups}


def test_group_sync_paginates_groups_members_and_enterprise_users() -> None:
    # 3 groups and 3 members per group, with a fake page size of 2, force the
    # offset loops (groups + memberships) and the marker loop (users) to run
    # more than once each.
    groups = [GroupFull(id=f"g{i}", name=f"Group {i}") for i in range(1, 4)]
    members_by_group = {
        "g1": [UserMini(id=str(i), login=f"g1u{i}@x.com") for i in range(3)],
        "g2": [UserMini(id=str(i), login=f"g2u{i}@x.com") for i in range(3)],
        "g3": [],
    }
    all_users = {f"ent{i}@x.com": str(i) for i in range(5)}
    fake = FakeBoxClient(
        folders_by_id={},
        pages={},
        groups=groups,
        members_by_group=members_by_group,
        users_by_login=all_users,
        page_size=2,
    )

    result = _run_group_sync(fake)

    # every real group surfaced despite spanning multiple offset pages
    assert box_group_id("g1") in result
    assert box_group_id("g2") in result
    assert box_group_id("g3") in result

    # membership pagination collected all 3 members of g1 (spans 2 pages)
    assert result[box_group_id("g1")] == ["g1u0@x.com", "g1u1@x.com", "g1u2@x.com"]
    # a group with no members yields an empty list, not a missing entry
    assert result[box_group_id("g3")] == []

    # the synthetic enterprise-all-users group collected every user across the
    # marker-paginated /users listing
    enterprise = result[box_all_enterprise_users_group_id(_ENTERPRISE_ID)]
    assert enterprise == sorted(all_users)


def test_group_sync_skips_group_whose_membership_fetch_fails() -> None:
    # One group's membership fetch errors; the sync must skip just that group
    # (not blank it, not abort) and still emit the healthy group + the
    # enterprise-all-users group.
    groups = [GroupFull(id=f"g{i}", name=f"Group {i}") for i in range(1, 3)]
    fake = FakeBoxClient(
        folders_by_id={},
        pages={},
        groups=groups,
        members_by_group={"g1": [UserMini(id="1", login="g1u@x.com")], "g2": []},
        membership_fail_status_by_group={"g2": 500},
        users_by_login={"ent@x.com": "1"},
        page_size=2,
    )

    result = _run_group_sync(fake)

    assert result[box_group_id("g1")] == ["g1u@x.com"]
    # the failing group is omitted entirely, not yielded with empty members
    assert box_group_id("g2") not in result
    assert box_all_enterprise_users_group_id(_ENTERPRISE_ID) in result


def test_group_sync_skips_group_exceeding_offset_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A group with more members than the offset ceiling can page must be skipped
    # entirely (preserving its prior membership), not yielded as a partial group
    # that would revoke access for the omitted members.
    monkeypatch.setattr(group_sync_module, "_MAX_OFFSET", 4)
    groups = [GroupFull(id="big", name="Big"), GroupFull(id="small", name="Small")]
    fake = FakeBoxClient(
        folders_by_id={},
        pages={},
        groups=groups,
        members_by_group={
            "big": [UserMini(id=str(i), login=f"b{i}@x.com") for i in range(6)],
            "small": [UserMini(id="1", login="s@x.com")],
        },
        users_by_login={"e@x.com": "1"},
        page_size=2,
    )

    result = _run_group_sync(fake)

    assert box_group_id("small") in result
    assert box_group_id("big") not in result
    assert box_all_enterprise_users_group_id(_ENTERPRISE_ID) in result


def test_group_sync_no_groups_still_emits_enterprise_group() -> None:
    fake = FakeBoxClient(
        folders_by_id={},
        pages={},
        groups=[],
        members_by_group={},
        users_by_login={"only@x.com": "1"},
        page_size=2,
    )
    result = _run_group_sync(fake)
    assert set(result) == {box_all_enterprise_users_group_id(_ENTERPRISE_ID)}
    assert result[box_all_enterprise_users_group_id(_ENTERPRISE_ID)] == ["only@x.com"]
