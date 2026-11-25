from unittest.mock import patch

import pytest

from ee.onyx.external_permissions.microsoft_utils.principal_sets import (
    everyone_term,
    group_term,
)
from ee.onyx.external_permissions.smb import group_sync
from ee.onyx.external_permissions.smb.directory import ActiveDirectory
from ee.onyx.external_permissions.smb.exclusion_groups import (
    exclusion_group_id,
    parse_exclusion_group_id,
)
from ee.onyx.external_permissions.smb.group_sync import domain_groups
from onyx.connectors.smb.models import EmailAttribute
from onyx.connectors.smb.sid import (
    MalformedSidError,
    domain_sid_of,
    rid_of,
    sid_from_bytes,
)
from tests.unit.ee.onyx.external_permissions.smb.smb_fakes import (
    ALICE,
    BOB,
    CAROL,
    DOMAIN_SID,
    DOMAIN_USERS,
    ENGINEERING,
    RESTRICTED,
    directory_ops,
)

LOCAL_GROUP = "S-1-5-32-545"


def _groups(
    exclusion_group_ids: set[str] | None = None,
    email_attribute: EmailAttribute = EmailAttribute.MAIL,
) -> dict[str, list[str]]:
    return {
        group.id: group.user_emails
        for group in domain_groups(
            directory_ops(), email_attribute, exclusion_group_ids or set()
        )
    }


def test_group_sync_yields_bare_sids_with_lowercase_emails() -> None:
    groups = _groups()

    assert groups[ENGINEERING] == ["alice@example.com", "bob@example.com"]
    # A disabled account cannot sign in, so it is in no group.
    assert groups[RESTRICTED] == ["carol@example.com"]


def test_the_everyone_group_holds_each_enabled_user_and_is_scoped_to_the_domain() -> (
    None
):
    groups = _groups()

    assert groups[f"ad_domain_everyone:{DOMAIN_SID}"] == [
        "alice@example.com",
        "bob@example.com",
        "carol@example.com",
        "svc@corp.example.com",
    ]


def test_the_email_attribute_option_reads_only_the_user_principal_name() -> None:
    groups = _groups(email_attribute=EmailAttribute.USER_PRINCIPAL_NAME)

    # Bob has no user principal name, so he maps to nobody.
    assert groups[ENGINEERING] == ["alice@corp"]


def test_an_exclusion_group_syncs_its_base_minus_the_excluded() -> None:
    domain_minus_group = exclusion_group_id(
        everyone_term(excluded_groups=[RESTRICTED]), DOMAIN_SID
    )
    group_minus_user = exclusion_group_id(
        group_term(ENGINEERING, excluded_users=[BOB]), DOMAIN_SID
    )

    groups = _groups({domain_minus_group, group_minus_user, "ad_except:garbage"})

    assert groups[domain_minus_group] == [
        "alice@example.com",
        "bob@example.com",
        "svc@corp.example.com",
    ]
    assert groups[group_minus_user] == ["alice@example.com"]
    assert "ad_except:garbage" not in groups


def test_an_exclusion_group_id_survives_the_lowercase_storage_round_trip() -> None:
    term = group_term(ENGINEERING, excluded_users=[ALICE], excluded_groups=[RESTRICTED])

    stored = exclusion_group_id(term, DOMAIN_SID)

    assert stored == stored.lower()
    assert parse_exclusion_group_id(stored, DOMAIN_SID) == term
    assert parse_exclusion_group_id(stored, "S-1-5-21-9-9-9") == term
    # A whole-domain term belongs to one domain only.
    everyone = exclusion_group_id(everyone_term(excluded_users=[CAROL]), DOMAIN_SID)
    assert parse_exclusion_group_id(everyone, "S-1-5-21-9-9-9") is None


def test_a_sid_the_domain_does_not_know_is_a_group_of_nobody() -> None:
    ops = directory_ops()
    directory = ActiveDirectory(ops, EmailAttribute.MAIL)

    assert directory.group(LOCAL_GROUP) is None
    assert directory.group_members(LOCAL_GROUP) == frozenset()
    assert not directory.is_user(LOCAL_GROUP)
    assert directory.is_user(ALICE.lower())


def test_the_directory_reads_users_and_each_group_once() -> None:
    ops = directory_ops()
    directory = ActiveDirectory(ops, EmailAttribute.MAIL)

    for _ in range(3):
        directory.all_users()
        directory.group_members(DOMAIN_USERS)

    assert ops.list_directory_users.call_count == 3  # five users, two per page
    assert ops.list_group_member_sids.call_count == 1


def test_group_sync_stops_at_the_permission_sync_timeout() -> None:
    with (
        patch.object(group_sync, "PERMISSION_SYNC_TIMEOUT", -1),
        pytest.raises(RuntimeError, match="timeout"),
    ):
        _groups()


def test_sid_bytes_parse_to_the_string_form() -> None:
    # S-1-5-21-1-2-3-513
    data = bytes.fromhex("01050000000000051500000001000000020000000300000001020000")

    assert sid_from_bytes(data) == "S-1-5-21-1-2-3-513"
    assert sid_from_bytes(b"\x00" + data, offset=1) == "S-1-5-21-1-2-3-513"
    assert domain_sid_of("S-1-5-21-1-2-3-513") == "S-1-5-21-1-2-3"
    assert domain_sid_of("S-1-5-32-545") is None
    assert rid_of("S-1-5-21-1-2-3-513") == 513
    with pytest.raises(MalformedSidError):
        sid_from_bytes(data[:-2])
