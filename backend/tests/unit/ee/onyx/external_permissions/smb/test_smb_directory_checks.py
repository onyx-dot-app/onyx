from unittest.mock import MagicMock

import pytest

from ee.onyx.external_permissions.smb.capability_checks import (
    DIRECTORY_BIND_CHECK_ID,
    DIRECTORY_GROUP_MEMBERS_CHECK_ID,
    DIRECTORY_USERS_CHECK_ID,
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
from onyx.connectors.smb.models import DirectoryUser
from tests.unit.ee.onyx.external_permissions.smb.smb_fakes import (
    DOMAIN_SID,
    directory_ops,
)


def _check(check_id: str) -> CapabilityCheck:
    return next(
        check for check in build_smb_group_sync_checks() if check.check_id == check_id
    )


def _context(
    gateway: MagicMock, ldap_host: str = "dc1.corp.example.com", **config: str
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
