"""A typed account's .pfx certificate, sent as base64 in credential_json, is
checked as the private-key upload checks the file."""

import base64

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import BestAvailableEncryption, pkcs12

from onyx.configs.constants import DocumentSource
from onyx.server.documents.private_key_types import validate_pkcs12_credential_value


def _pfx_base64() -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    pfx = pkcs12.serialize_key_and_certificates(
        b"onyx", key, None, None, BestAvailableEncryption(b"secret")
    )
    return base64.b64encode(pfx).decode("ascii")


@pytest.mark.parametrize(
    ("source", "key"),
    [
        (DocumentSource.SHAREPOINT, "sp_private_key"),
        (DocumentSource.ONEDRIVE, "onedrive_private_key"),
        (DocumentSource.TEAMS, "teams_private_key"),
        (DocumentSource.OUTLOOK, "outlook_private_key"),
    ],
)
def test_accepts_a_pfx_certificate(source: DocumentSource, key: str) -> None:
    validate_pkcs12_credential_value(source, {key: _pfx_base64()})


def test_accepts_an_account_without_a_certificate() -> None:
    validate_pkcs12_credential_value(
        DocumentSource.SHAREPOINT, {"sp_client_secret": "secret"}
    )


def test_rejects_text_that_is_not_base64() -> None:
    with pytest.raises(ValueError, match="not valid base64"):
        validate_pkcs12_credential_value(
            DocumentSource.SHAREPOINT, {"sp_private_key": "not base64!"}
        )


def test_rejects_a_file_that_is_not_pkcs12() -> None:
    not_pfx = base64.b64encode(b"just some text, not a certificate").decode()
    with pytest.raises(ValueError, match="not a valid PKCS#12"):
        validate_pkcs12_credential_value(
            DocumentSource.SHAREPOINT, {"sp_private_key": not_pfx}
        )


def test_ignores_sources_without_a_certificate() -> None:
    validate_pkcs12_credential_value(
        DocumentSource.CONFLUENCE, {"sp_private_key": "not base64!"}
    )
