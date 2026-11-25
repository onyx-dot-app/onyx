import os
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.exceptions import CredentialInvalidError
from onyx.connectors.smb import kerberos_config, source_operations
from onyx.connectors.smb.models import SmbAuthMethod, SmbCredentials
from onyx.connectors.smb.source_operations import SmbSourceOperations

KERBEROS_CREDENTIAL = {
    "authentication_method": "kerberos",
    "smb_domain": "CORP",
    "smb_username": "CORP\\svc-onyx",
    "smb_password": "secret",
    "kerberos_realm": "corp.example.com",
    "kerberos_kdc": "dc1.corp.example.com",
}


@pytest.fixture
def kerberos_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[Path, None, None]:
    """An empty settings file for one test. The process state is put back."""
    path = tmp_path / "krb5.conf"
    monkeypatch.setattr(kerberos_config, "_kdcs", {})
    monkeypatch.setattr(kerberos_config, "_kdc_hosts", {})
    monkeypatch.setattr(kerberos_config, "_host_realms", {})
    monkeypatch.setattr(kerberos_config, "_config_path", None)
    monkeypatch.setattr(
        kerberos_config.tempfile,
        "mkdtemp",
        lambda prefix: str(tmp_path),  # noqa: ARG005
    )
    monkeypatch.setenv("KRB5_CONFIG", "/etc/krb5.conf")
    yield path


def test_a_kerberos_credential_needs_a_realm_and_signs_in_as_user_at_realm() -> None:
    credentials = SmbCredentials.model_validate(KERBEROS_CREDENTIAL)

    assert credentials.authentication_method is SmbAuthMethod.KERBEROS
    assert credentials.kerberos_realm == "CORP.EXAMPLE.COM"
    # The realm names the domain, so the domain prefix is dropped.
    assert credentials.kerberos_principal == "svc-onyx@CORP.EXAMPLE.COM"
    with pytest.raises(ValidationError):
        SmbCredentials.model_validate({**KERBEROS_CREDENTIAL, "kerberos_realm": ""})


def test_a_realm_is_written_ahead_of_the_system_settings(
    kerberos_settings: Path,
) -> None:
    kerberos_config.register_realm(
        "CORP.EXAMPLE.COM",
        "dc1.corp.example.com",
        ["10.0.0.5"],
        ["FS01.files.example.net"],
    )
    kerberos_config.register_realm("OTHER.EXAMPLE.COM", None, [], [])

    text = kerberos_settings.read_text()
    # The checked address, not the name that could resolve differently later.
    assert "CORP.EXAMPLE.COM = {\n        kdc = 10.0.0.5\n    }" in text
    # The server's DNS domain differs from the realm's name.
    assert "fs01.files.example.net = CORP.EXAMPLE.COM" in text
    assert "OTHER.EXAMPLE.COM" not in text
    # A host that DNS names would skip the network policy.
    assert "dns_lookup_kdc = false" in text
    assert os.environ["KRB5_CONFIG"] == f"{kerberos_settings}:/etc/krb5.conf"


def test_a_second_credential_cannot_move_a_realm_or_a_server(
    kerberos_settings: Path,
) -> None:
    """The settings are shared, so the first credential decides."""
    kerberos_config.register_realm(
        "CORP.EXAMPLE.COM", "dc1.corp.example.com", ["10.0.0.5"], ["fs01"]
    )

    with pytest.raises(kerberos_config.KerberosConflictError, match="KDC"):
        kerberos_config.register_realm(
            "CORP.EXAMPLE.COM", "rogue.example.net", ["203.0.113.9"], []
        )
    with pytest.raises(kerberos_config.KerberosConflictError, match="realm"):
        kerberos_config.register_realm("ROGUE.EXAMPLE.NET", None, [], ["fs01"])

    text = kerberos_settings.read_text()
    assert "203.0.113.9" not in text and "ROGUE" not in text
    # The same values again are no conflict.
    kerberos_config.register_realm(
        "CORP.EXAMPLE.COM", "DC1.corp.example.com", ["10.0.0.5"], ["fs01"]
    )


@pytest.mark.parametrize(
    "realm, kdc, host",
    [
        ("CORP.EXAMPLE.COM\n[libdefaults]", None, "fs01"),
        ("CORP.EXAMPLE.COM", "dc1 }\n evil = {", "fs01"),
        ("CORP.EXAMPLE.COM", None, "fs01 = EVIL.REALM\nx"),
    ],
)
def test_a_value_that_could_change_the_settings_file_is_refused(
    kerberos_settings: Path, realm: str, kdc: str | None, host: str
) -> None:
    with pytest.raises(ValueError, match="not allowed"):
        kerberos_config.register_realm(realm, kdc, [], [host])

    assert not kerberos_settings.exists()


def _gateway(credential: dict[str, str]) -> SmbSourceOperations:
    return SmbSourceOperations(
        credentials_provider=OnyxStaticCredentialsProvider(
            None, DocumentSource.SMB.value, credential
        ),
        connector_specific_config={"host": "fs01.corp.example.com", "share": "Plans"},
    )


def test_a_kerberos_session_signs_in_with_the_principal_and_checks_the_kdc(
    kerberos_settings: Path,
) -> None:
    session = MagicMock()
    session.connection.dialect = 0x311
    session.connection.transport._sock = None
    with (
        patch.object(source_operations, "validate_network_host") as policy,
        patch.object(source_operations, "_kerberos_library"),
        patch.object(
            source_operations, "_resolve_addresses", return_value=["10.0.0.5"]
        ),
        patch.object(
            source_operations.smbclient, "register_session", return_value=session
        ) as register,
    ):
        _gateway(KERBEROS_CREDENTIAL).connect()

    assert register.call_args.kwargs["auth_protocol"] == "kerberos"
    assert register.call_args.kwargs["username"] == "svc-onyx@CORP.EXAMPLE.COM"
    assert register.call_args.kwargs["require_signing"] is True
    checked = [call.args for call in policy.call_args_list]
    assert ("dc1.corp.example.com", "Kerberos KDC") in checked
    assert ("10.0.0.5", "Kerberos KDC address") in checked
    text = kerberos_settings.read_text()
    assert "kdc = 10.0.0.5" in text
    assert "fs01.corp.example.com = CORP.EXAMPLE.COM" in text


def test_a_username_of_another_realm_is_refused(kerberos_settings: Path) -> None:  # noqa: ARG001
    credential = {**KERBEROS_CREDENTIAL, "smb_username": "svc@OTHER.EXAMPLE.NET"}

    with (
        patch.object(source_operations, "_kerberos_library"),
        pytest.raises(CredentialInvalidError, match="OTHER.EXAMPLE.NET"),
    ):
        _gateway(credential).get_kerberos_ticket()


def test_an_ntlm_credential_asks_for_no_ticket() -> None:
    ntlm = {"smb_domain": "CORP", "smb_username": "svc", "smb_password": "secret"}

    assert _gateway(ntlm).get_kerberos_ticket() is None


def test_a_bad_kdc_host_is_a_credential_error(kerberos_settings: Path) -> None:  # noqa: ARG001
    credential = {**KERBEROS_CREDENTIAL, "kerberos_kdc": "dc1\n[realms]"}

    with (
        patch.object(source_operations, "validate_network_host"),
        patch.object(source_operations, "_kerberos_library"),
        patch.object(source_operations, "_resolve_addresses", return_value=[]),
        pytest.raises(CredentialInvalidError, match="Kerberos settings"),
    ):
        _gateway(credential).get_kerberos_ticket()
