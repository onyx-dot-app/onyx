from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from ee.onyx.external_permissions.smb.capability_checks import (
    DIRECTORY_BIND_CHECK_ID,
    DIRECTORY_GROUP_MEMBERS_CHECK_ID,
    DIRECTORY_USERS_CHECK_ID,
    SHARE_PERMISSIONS_CHECK_ID,
    SID_RESOLUTION_CHECK_ID,
    build_smb_doc_permission_sync_checks,
    build_smb_group_sync_checks,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CheckOutput,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    InconclusiveValidationError,
)
from onyx.connectors.smb.models import DirectoryUser, SmbEntry
from onyx.connectors.smb.security_descriptor import (
    Ace,
    AceKind,
    SecurityDescriptor,
)
from tests.unit.ee.onyx.external_permissions.smb.smb_fakes import (
    DOMAIN_SID,
    ENGINEERING,
    directory_ops,
)


def _check(check_id: str) -> CapabilityCheck:
    return next(
        check for check in build_smb_group_sync_checks() if check.check_id == check_id
    )


def _context(
    gateway: MagicMock, ldap_host: str = "dc1.corp.example.com", **config: str | bool
) -> CapabilityCheckContext:
    return CapabilityCheckContext(
        source=DocumentSource.SMB,
        credential_json={
            "smb_domain": "CORP",
            "smb_username": "svc-onyx",
            "smb_password": "secret",
            "ldap_host": ldap_host,
        },
        connector_specific_config={"host": "fs01", "share": "Plans", **config},
        source_operations=gateway,
    )


def test_bind_needs_an_ldap_host_and_names_the_domain() -> None:
    gateway = directory_ops()

    output = _check(DIRECTORY_BIND_CHECK_ID).run(_context(gateway))

    assert isinstance(output, CheckOutput)
    assert output.summary == "Signed in to DC=corp,DC=example,DC=com"
    with pytest.raises(ConnectorValidationError, match="LDAP host"):
        _check(DIRECTORY_BIND_CHECK_ID).run(_context(gateway, ldap_host=""))


def test_users_check_reports_the_share_of_users_without_an_address() -> None:
    gateway = directory_ops(
        [
            DirectoryUser(sid=f"{DOMAIN_SID}-1", mail="a@example.com"),
            DirectoryUser(sid=f"{DOMAIN_SID}-2"),
            DirectoryUser(sid=f"{DOMAIN_SID}-3", mail="c@example.com", enabled=False),
        ]
    )

    output = _check(DIRECTORY_USERS_CHECK_ID).run(_context(gateway))

    assert isinstance(output, CheckOutput)
    assert output.summary == "1 of the first 2 enabled users have an email address"
    assert len(output.advisories) == 1


def test_users_check_fails_when_no_user_would_get_access() -> None:
    gateway = directory_ops(
        [DirectoryUser(sid=f"{DOMAIN_SID}-1", mail="a@example.com")]
    )

    with pytest.raises(ConnectorValidationError, match="userPrincipalName"):
        _check(DIRECTORY_USERS_CHECK_ID).run(
            _context(gateway, email_attribute="userPrincipalName")
        )
    with pytest.raises(InconclusiveValidationError):
        _check(DIRECTORY_USERS_CHECK_ID).run(_context(directory_ops([])))


def test_group_members_check_finds_domain_users_by_sid() -> None:
    gateway = directory_ops()

    output = _check(DIRECTORY_GROUP_MEMBERS_CHECK_ID).run(_context(gateway))

    assert isinstance(output, CheckOutput)
    assert output.summary is not None and output.summary.startswith(
        "Read the 5 members"
    )
    assert gateway.find_directory_group.call_args.kwargs["sid"] == f"{DOMAIN_SID}-513"


def _doc_check(check_id: str) -> CapabilityCheck:
    return next(
        check
        for check in build_smb_doc_permission_sync_checks()
        if check.check_id == check_id
    )


def test_perm_sync_fails_until_an_admin_confirms_the_share_permissions() -> None:
    gateway = directory_ops()

    with pytest.raises(ConnectorValidationError, match="NTFS permissions only"):
        _doc_check(SHARE_PERMISSIONS_CHECK_ID).run(_context(gateway))
    output = _doc_check(SHARE_PERMISSIONS_CHECK_ID).run(
        _context(gateway, share_permissions_confirmed=True)
    )

    assert isinstance(output, CheckOutput)


def _share(gateway: MagicMock, lists: dict[str, list[Ace]]) -> None:
    """A share whose top folder holds one file per key of ``lists``."""
    changed = datetime(2026, 1, 1, tzinfo=timezone.utc)
    gateway.list_folder.return_value = [
        SmbEntry(
            name=name,
            attributes=0,
            creation_time=changed,
            last_write_time=changed,
            change_time=changed,
            size=1,
        )
        for name in lists
        if name
    ]
    gateway.read_security_descriptor.side_effect = lambda *, path: SecurityDescriptor(
        dacl_present=True, aces=lists[path]
    )


def _allow(sid: str) -> Ace:
    return Ace(kind=AceKind.ALLOW, sid=sid, mask=0x1)


def test_sid_check_reports_files_that_only_local_groups_can_read() -> None:
    gateway = directory_ops()
    _share(
        gateway,
        {
            "": [_allow(ENGINEERING)],
            "a.txt": [_allow(ENGINEERING), _allow("S-1-5-32-545")],
            "local.txt": [_allow("S-1-5-32-545")],
            "denied.txt": [
                Ace(kind=AceKind.DENY, sid="S-1-5-32-545", mask=0x1),
                _allow(ENGINEERING),
            ],
        },
    )

    output = _doc_check(SID_RESOLUTION_CHECK_ID).run(_context(gateway))

    assert isinstance(output, CheckOutput)
    assert output.summary == (
        "2 of 4 sampled access lists resolve to domain users or groups"
    )
    messages = " ".join(advisory.message for advisory in output.advisories)
    assert "S-1-5-32-545" in messages
    assert "local.txt" in messages and "denied.txt" in messages


def test_sid_check_fails_when_no_sampled_file_would_be_visible() -> None:
    gateway = directory_ops()
    _share(
        gateway,
        {"": [_allow("S-1-5-32-545")], "a.txt": [_allow("S-1-5-32-545")]},
    )

    with pytest.raises(ConnectorValidationError, match="S-1-5-32-545"):
        _doc_check(SID_RESOLUTION_CHECK_ID).run(_context(gateway))
