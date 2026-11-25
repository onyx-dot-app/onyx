"""The NTFS access list of a file, as the readers Onyx stores for it."""

import struct
from unittest.mock import MagicMock

import pytest

from ee.onyx.external_permissions.microsoft_utils.principal_sets import (
    everyone_term,
    group_term,
)
from ee.onyx.external_permissions.smb.access import SmbAccessResolver
from ee.onyx.external_permissions.smb.acl import (
    UnresolvableDenyError,
    dacl_readers,
)
from ee.onyx.external_permissions.smb.directory import ActiveDirectory
from ee.onyx.external_permissions.smb.exclusion_groups import exclusion_group_id
from onyx.access.models import ExternalAccess
from onyx.connectors.smb.models import EmailAttribute
from onyx.connectors.smb.security_descriptor import (
    Ace,
    AceKind,
    MalformedSecurityDescriptorError,
    SecurityDescriptor,
    parse_security_descriptor,
)
from onyx.connectors.smb.source_operations import (
    SmbAccessDeniedError,
    SmbNotFoundError,
    SmbRequestError,
)
from tests.unit.ee.onyx.external_permissions.smb.smb_fakes import (
    ALICE,
    BOB,
    CAROL,
    DISABLED_DAVE,
    DOMAIN_SID,
    DOMAIN_USERS,
    ENGINEERING,
    RESTRICTED,
    directory_ops,
)

READ = 0x00120089  # FILE_GENERIC_READ
WRITE_ONLY = 0x00000002
FULL = 0x001F01FF
GENERIC_READ = 0x80000000
GENERIC_ALL = 0x10000000

EVERYONE = "S-1-1-0"
AUTHENTICATED_USERS = "S-1-5-11"
SYSTEM = "S-1-5-18"
ADMINISTRATORS = "S-1-5-32-544"
BUILTIN_USERS = "S-1-5-32-545"
LOCAL_ACCOUNT = "S-1-5-21-7-7-7-1001"
EVERYONE_GROUP = f"ad_domain_everyone:{DOMAIN_SID}"


def allow(sid: str, mask: int = READ, **flags: bool) -> Ace:
    return Ace(kind=AceKind.ALLOW, sid=sid, mask=mask, **flags)


def deny(sid: str, mask: int = READ, **flags: bool) -> Ace:
    return Ace(kind=AceKind.DENY, sid=sid, mask=mask, **flags)


def _access(*aces: Ace, dacl_present: bool = True) -> ExternalAccess:
    ops = directory_ops()
    ops.read_security_descriptor.return_value = SecurityDescriptor(
        dacl_present=dacl_present, aces=list(aces)
    )
    resolver = SmbAccessResolver(ops, EmailAttribute.MAIL)
    return resolver.paths_access(["plan.txt"])["plan.txt"]


def _readers(access: ExternalAccess) -> tuple[set[str], set[str]]:
    assert access.is_public is False
    return access.external_user_emails, access.external_user_group_ids


@pytest.mark.parametrize(
    "aces, emails, groups",
    [
        # A user and a group, each by its own id.
        ([allow(ALICE), allow(ENGINEERING)], {"alice@example.com"}, {ENGINEERING}),
        # Read rights in each of their forms.
        ([allow(ALICE, GENERIC_READ)], {"alice@example.com"}, set()),
        ([allow(ALICE, GENERIC_ALL)], {"alice@example.com"}, set()),
        ([allow(ALICE, FULL)], {"alice@example.com"}, set()),
        # A right that is not read grants nothing.
        ([allow(ALICE, WRITE_ONLY)], set(), set()),
        # An entry that only children inherit does not apply to its holder.
        ([allow(ALICE, inherit_only=True)], set(), set()),
        # A condition that Onyx cannot evaluate grants nothing.
        ([allow(ALICE, qualified=True)], set(), set()),
        # A disabled user cannot sign in.
        ([allow(DISABLED_DAVE)], set(), set()),
        # Everyone, Authenticated Users and Domain Users are the domain's
        # users, and never the public.
        ([allow(EVERYONE)], set(), {EVERYONE_GROUP}),
        ([allow(AUTHENTICATED_USERS)], set(), {EVERYONE_GROUP}),
        ([allow(DOMAIN_USERS)], set(), {EVERYONE_GROUP}),
        # Service principals and the file server's local principals grant
        # nothing, which fails closed.
        (
            [
                allow(SYSTEM, FULL),
                allow(ADMINISTRATORS, FULL),
                allow(BUILTIN_USERS),
                allow(LOCAL_ACCOUNT),
            ],
            set(),
            set(),
        ),
    ],
)
def test_allow_entries(aces: list[Ace], emails: set[str], groups: set[str]) -> None:
    assert _readers(_access(*aces)) == (emails, groups)


def test_a_deny_entry_removes_its_user_from_a_later_group() -> None:
    access = _access(deny(BOB), allow(ENGINEERING), allow(BOB))

    assert _readers(access) == (
        set(),
        {exclusion_group_id(group_term(ENGINEERING, excluded_users=[BOB]), DOMAIN_SID)},
    )


def test_a_deny_entry_removes_its_group_from_later_everyone() -> None:
    access = _access(deny(RESTRICTED), allow(EVERYONE), allow(CAROL))

    assert _readers(access) == (
        set(),
        {exclusion_group_id(everyone_term(excluded_groups=[RESTRICTED]), DOMAIN_SID)},
    )


def test_an_allow_entry_before_a_deny_entry_still_grants() -> None:
    """Windows stops at the first entry that decides, so the order matters in
    a list that is not in canonical order."""
    access = _access(allow(ENGINEERING), deny(BOB), allow(BOB), allow(CAROL))

    assert _readers(access) == ({"carol@example.com"}, {ENGINEERING})


def test_a_deny_of_another_right_does_not_remove_read() -> None:
    assert _readers(_access(deny(BOB, WRITE_ONLY), allow(BOB))) == (
        {"bob@example.com"},
        set(),
    )


def test_a_deny_for_everyone_stops_every_later_grant() -> None:
    access = _access(allow(ALICE), deny(EVERYONE), allow(ENGINEERING))

    assert _readers(access) == ({"alice@example.com"}, set())


def test_a_deny_with_a_condition_counts_in_full() -> None:
    assert _readers(_access(deny(BOB, qualified=True), allow(BOB))) == (set(), set())


@pytest.mark.parametrize("sid", [BUILTIN_USERS, ADMINISTRATORS, LOCAL_ACCOUNT])
def test_a_deny_for_a_principal_onyx_cannot_name_makes_the_file_private(
    sid: str,
) -> None:
    assert _access(deny(sid), allow(EVERYONE)) == ExternalAccess.empty()
    with pytest.raises(UnresolvableDenyError):
        dacl_readers(
            SecurityDescriptor(dacl_present=True, aces=[deny(sid), allow(EVERYONE)]),
            ActiveDirectory(directory_ops(), EmailAttribute.MAIL),
        )


def test_a_deny_for_a_service_principal_is_ignored() -> None:
    assert _readers(_access(deny(SYSTEM), allow(ALICE))) == (
        {"alice@example.com"},
        set(),
    )


def test_a_missing_access_list_is_the_domain_and_never_public() -> None:
    assert _readers(_access(dacl_present=False)) == (set(), {EVERYONE_GROUP})


def test_an_empty_access_list_grants_nothing() -> None:
    assert _access() == ExternalAccess.empty()


def test_a_builtin_group_is_never_looked_up_in_the_domain() -> None:
    """A domain controller lists its own BUILTIN groups under the same SIDs."""
    ops = directory_ops()
    directory = ActiveDirectory(ops, EmailAttribute.MAIL)

    readers = dacl_readers(
        SecurityDescriptor(dacl_present=True, aces=[allow(BUILTIN_USERS)]), directory
    )

    assert not readers.principals
    assert readers.unknown_allow_sids == {BUILTIN_USERS}
    ops.find_directory_group.assert_not_called()


def _resolver_with(side_effect: object) -> tuple[SmbAccessResolver, MagicMock]:
    ops = directory_ops()
    ops.read_security_descriptor.side_effect = side_effect
    return SmbAccessResolver(ops, EmailAttribute.MAIL), ops


@pytest.mark.parametrize(
    "error", [SmbNotFoundError("gone"), SmbAccessDeniedError("denied")]
)
def test_a_path_whose_access_list_cannot_be_read_stays_private(
    error: Exception,
) -> None:
    resolver, _ = _resolver_with(error)

    assert resolver.paths_access(["a.txt"]) == {"a.txt": ExternalAccess.empty()}


def test_a_server_error_fails_the_sync_and_makes_nothing_private() -> None:
    resolver, _ = _resolver_with(SmbRequestError("server error", status_code=None))

    with pytest.raises(SmbRequestError):
        resolver.paths_access(["a.txt"])


def _sid_bytes(sid: str) -> bytes:
    parts = sid.split("-")
    sub_authorities = [int(part) for part in parts[3:]]
    return (
        bytes([1, len(sub_authorities)])
        + int(parts[2]).to_bytes(6, "big")
        + struct.pack(f"<{len(sub_authorities)}I", *sub_authorities)
    )


def _ace_bytes(
    ace_type: int, flags: int, mask: int, sid: str, extra: bytes = b""
) -> bytes:
    body = struct.pack("<I", mask) + extra + _sid_bytes(sid)
    return struct.pack("<BBH", ace_type, flags, 4 + len(body)) + body


def _descriptor_bytes(aces: list[bytes], control: int = 0x8004) -> bytes:
    acl_body = b"".join(aces)
    acl = struct.pack("<BBHHH", 2, 0, 8 + len(acl_body), len(aces), 0) + acl_body
    return struct.pack("<BBHIIII", 1, 0, control, 0, 0, 0, 20) + acl


def test_parser_reads_each_entry_type_in_stored_order() -> None:
    object_flags_and_guid = struct.pack("<I", 0x1) + bytes(16)
    data = _descriptor_bytes(
        [
            _ace_bytes(0x01, 0x00, READ, BOB),
            _ace_bytes(0x00, 0x00, FULL, ALICE),
            _ace_bytes(0x00, 0x0B, GENERIC_ALL, ENGINEERING),  # inherit only
            _ace_bytes(0x02, 0x00, READ, CAROL),  # an audit entry
            _ace_bytes(0x09, 0x00, READ, CAROL) + b"",  # allow with a condition
            _ace_bytes(0x06, 0x00, READ, CAROL, object_flags_and_guid),
        ]
    )

    descriptor = parse_security_descriptor(data)

    assert descriptor.dacl_present
    assert descriptor.aces == [
        deny(BOB),
        allow(ALICE, FULL),
        allow(ENGINEERING, GENERIC_ALL, inherit_only=True),
        allow(CAROL, qualified=True),
        deny(CAROL, qualified=True),
    ]


def test_parser_tells_a_missing_list_from_an_empty_one() -> None:
    missing = struct.pack("<BBHIIII", 1, 0, 0x8000, 0, 0, 0, 0)

    assert parse_security_descriptor(missing).dacl_present is False
    assert parse_security_descriptor(_descriptor_bytes([])) == SecurityDescriptor(
        dacl_present=True, aces=[]
    )


def test_parser_rejects_a_list_that_is_cut_off() -> None:
    data = _descriptor_bytes([_ace_bytes(0x00, 0x00, READ, ALICE)])

    with pytest.raises(MalformedSecurityDescriptorError):
        parse_security_descriptor(data[:-6])
    with pytest.raises(MalformedSecurityDescriptorError):
        parse_security_descriptor(data[:10])
