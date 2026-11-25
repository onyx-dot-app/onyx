from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest
from smbprotocol.exceptions import SMBConnectionClosed, SMBOSError

from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialInvalidError,
    UnreachableValidationError,
)
from onyx.connectors.smb import source_operations
from onyx.connectors.smb.source_operations import (
    STATUS_ACCESS_DENIED,
    SmbAccessDeniedError,
    SmbNotFoundError,
    SmbSourceOperations,
    validate_network_host,
)
from onyx.server.security.models import SSRFProtectionLevel

_OBJECT_NAME_NOT_FOUND = 0xC0000034
_LOGON_FAILURE = 0xC000006D


def _gateway(**config: object) -> SmbSourceOperations:
    return SmbSourceOperations(
        credentials_provider=OnyxStaticCredentialsProvider(
            None,
            DocumentSource.SMB.value,
            {"smb_domain": "CORP", "smb_username": "svc", "smb_password": "secret"},
        ),
        connector_specific_config={"host": "fs01", "share": "Plans", **config},
    )


@pytest.fixture
def register() -> Generator[MagicMock, None, None]:
    """``smbclient.register_session``, which returns a signed-in SMB 3.1.1
    session, behind a host that passed the network policy."""
    session = MagicMock()
    session.connection.dialect = 0x311
    session.connection.transport._sock = None
    with (
        patch.object(source_operations, "validate_network_host"),
        patch.object(
            source_operations.smbclient, "register_session", return_value=session
        ) as register_session,
    ):
        yield register_session


def test_session_requires_signing_ntlm_and_encryption_by_default(
    register: MagicMock,
) -> None:
    _gateway().connect()

    assert register.call_args.args == ("fs01",)
    kwargs = register.call_args.kwargs
    assert kwargs["username"] == "CORP\\svc"
    assert kwargs["require_signing"] is True
    assert kwargs["encrypt"] is True
    assert kwargs["auth_protocol"] == "ntlm"
    assert kwargs["port"] == 445


def test_encryption_can_be_left_to_the_server(register: MagicMock) -> None:
    register.return_value.encrypt_data = False
    register.return_value.signing_required = True

    info = _gateway(require_encryption=False).connect()

    assert register.call_args.kwargs["encrypt"] is None
    assert info.encrypted is False and info.signing_required is True


def test_a_dialect_below_smb_2_1_is_refused(register: MagicMock) -> None:
    register.return_value.connection.dialect = 0x202

    with pytest.raises(ConnectorValidationError, match="SMB 2.1 or later"):
        _gateway().connect()


@pytest.mark.parametrize(
    "raised, expected",
    [
        (SMBOSError(_LOGON_FAILURE, "x"), CredentialInvalidError),
        (SMBOSError(STATUS_ACCESS_DENIED, "x"), SmbAccessDeniedError),
        (SMBOSError(_OBJECT_NAME_NOT_FOUND, "x"), SmbNotFoundError),
        (ValueError("Failed to connect to 'fs01:445'"), UnreachableValidationError),
    ],
)
def test_server_errors_map_to_what_the_walk_acts_on(
    register: MagicMock,  # noqa: ARG001
    raised: Exception,
    expected: type[Exception],
) -> None:
    with (
        patch.object(source_operations.smbclient, "scandir", side_effect=raised),
        pytest.raises(expected),
    ):
        _gateway().list_folder(path="Projects")


def test_a_missing_share_root_reads_as_a_missing_share(
    register: MagicMock,  # noqa: ARG001
) -> None:
    with (
        patch.object(
            source_operations.smbclient,
            "scandir",
            side_effect=SMBOSError(_OBJECT_NAME_NOT_FOUND, "x"),
        ),
        pytest.raises(ConnectorValidationError, match="share 'Plans' does not exist"),
    ):
        _gateway().list_folder(path="")


def test_a_closed_connection_is_made_again_once(
    register: MagicMock,  # noqa: ARG001
) -> None:
    with patch.object(
        source_operations.smbclient,
        "scandir",
        side_effect=[SMBConnectionClosed("closed"), iter([])],
    ) as scandir:
        assert _gateway().list_folder(path="Projects") == []

    assert scandir.call_count == 2


def test_the_file_server_is_refused_on_a_multi_tenant_deployment() -> None:
    with (
        patch.object(source_operations, "MULTI_TENANT", True),
        pytest.raises(ConnectorValidationError, match="self-hosted"),
    ):
        validate_network_host("fs01.corp.example.com", "file server")


@pytest.mark.parametrize(
    "level, reachable",
    [
        (SSRFProtectionLevel.VALIDATE_ALL, False),
        (SSRFProtectionLevel.VALIDATE_LLM, True),
    ],
)
def test_a_private_host_follows_the_ssrf_protection_level(
    level: SSRFProtectionLevel, reachable: bool
) -> None:
    settings = MagicMock(ssrf_protection_level=level)
    with patch.object(
        source_operations, "get_security_settings", return_value=settings
    ):
        if reachable:
            validate_network_host("10.1.2.3", "file server")
            return
        with pytest.raises(ConnectorValidationError, match="SSRF protection level"):
            validate_network_host("10.1.2.3", "file server")


def test_cloud_metadata_is_never_reachable() -> None:
    settings = MagicMock(ssrf_protection_level=SSRFProtectionLevel.DISABLED)
    with (
        patch.object(source_operations, "get_security_settings", return_value=settings),
        pytest.raises(ConnectorValidationError),
    ):
        validate_network_host("169.254.169.254", "file server")
