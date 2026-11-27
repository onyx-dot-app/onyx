import pytest
from pydantic import ValidationError

from onyx.connectors.smb.config import SmbConnectorConfig
from onyx.connectors.smb.models import SmbCredentials


def test_config_normalizes_what_an_admin_pastes() -> None:
    config = SmbConnectorConfig.model_validate(
        {
            "host": " \\\\FS01.corp.example.com\\ ",
            "share": "\\Plans\\",
            "path_prefix": "\\Projects\\2026\\",
            "excluded_paths": ["b\\x", "/a/", "b/x", ""],
        }
    )

    assert config.host == "FS01.corp.example.com"
    assert config.share == "Plans"
    assert config.path_prefix == "Projects/2026"
    # Sorted and without duplicates, so one set has one stored form.
    assert config.excluded_paths == ["a", "b/x"]
    assert config.require_encryption is True
    assert config.index_offline_files is False


@pytest.mark.parametrize(
    "values",
    [
        {"host": "fs01/Plans", "share": "Plans"},
        {"host": "fs01", "share": "Plans\\Projects"},
        {"host": "fs01", "share": "IPC$"},
        {"host": "fs01", "share": "Plans", "path_prefix": "a/../b"},
        {"host": "fs01", "share": "Plans", "excluded_paths": ["../other"]},
        {"host": "fs01", "share": "Plans", "port": 0},
    ],
)
def test_config_rejects_values_that_name_another_place(values: dict) -> None:
    with pytest.raises(ValidationError):
        SmbConnectorConfig.model_validate(values)


@pytest.mark.parametrize(
    "domain, username, account",
    [
        ("CORP", "svc-onyx", "CORP\\svc-onyx"),
        ("CORP", "OTHER\\svc-onyx", "OTHER\\svc-onyx"),
        ("corp.example.com", "svc-onyx@corp.example.com", "svc-onyx@corp.example.com"),
        ("", "localuser", "localuser"),
    ],
)
def test_account_name_adds_the_domain_once(
    domain: str, username: str, account: str
) -> None:
    credentials = SmbCredentials(
        smb_domain=domain, smb_username=username, smb_password="secret"
    )

    assert credentials.account_name == account


def test_credential_errors_do_not_echo_the_password() -> None:
    with pytest.raises(ValidationError) as error:
        SmbCredentials.model_validate({"smb_username": "", "smb_password": "hunter2"})

    assert "hunter2" not in str(error.value)
