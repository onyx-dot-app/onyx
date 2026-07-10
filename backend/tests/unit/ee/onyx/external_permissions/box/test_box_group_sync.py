from typing import cast
from unittest.mock import MagicMock
from unittest.mock import patch

from box_sdk_gen import BoxClient
from box_sdk_gen.schemas.group_full import GroupFull
from box_sdk_gen.schemas.user_mini import UserMini

from ee.onyx.external_permissions.box.group_sync import box_group_sync
from onyx.connectors.box.connector import box_all_enterprise_users_group_id
from onyx.connectors.box.connector import box_group_id
from onyx.connectors.box.connector import BoxConnector
from onyx.db.models import ConnectorCredentialPair
from tests.unit.onyx.connectors.box.fake_box_client import FakeBoxClient


def _run_group_sync(fake: FakeBoxClient) -> dict[str, list[str]]:
    """Drive box_group_sync with the enterprise client stubbed to `fake`,
    returning {group_id: sorted member emails}."""
    cc_pair = MagicMock(spec=ConnectorCredentialPair)
    cc_pair.connector = MagicMock()
    cc_pair.connector.connector_specific_config = {}
    cc_pair.credential = MagicMock()
    cc_pair.credential.credential_json = MagicMock()
    cc_pair.credential.credential_json.get_value.return_value = {}

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
    enterprise = result[box_all_enterprise_users_group_id()]
    assert enterprise == sorted(all_users)


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
    assert set(result) == {box_all_enterprise_users_group_id()}
    assert result[box_all_enterprise_users_group_id()] == ["only@x.com"]
