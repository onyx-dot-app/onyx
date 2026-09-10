"""App-only Microsoft Entra authentication shared by the Microsoft connectors.

Connectors map their own credential field names onto :func:`build_msal_app`,
which takes explicit values so the package never has to know whether a field is
called ``sp_client_id`` or ``teams_client_id``.

Callers keep their own "app is not initialized" / "token acquisition failed"
guards: SharePoint raises ``ConnectorValidationError`` there, which cancels the
index attempt and marks the credential invalid, while Teams raises
``RuntimeError``, which only fails the attempt. Those differ on purpose.
"""

import base64
from enum import Enum
from typing import Any

import msal
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from pydantic import BaseModel

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.utils.logger import setup_logger

logger = setup_logger()


class MicrosoftAuthMethod(Enum):
    CLIENT_SECRET = "client_secret"
    CERTIFICATE = "certificate"


class CertificateData(BaseModel):
    """Data class for storing certificate information loaded from PFX file."""

    private_key: bytes
    thumbprint: str


def load_certificate_from_pfx(pfx_data: bytes, password: str) -> CertificateData | None:
    """Load certificate from .pfx file for MSAL authentication"""
    try:
        # Load the certificate and private key
        private_key, certificate, additional_certificates = (
            pkcs12.load_key_and_certificates(pfx_data, password.encode("utf-8"))
        )

        # Validate that certificate and private key are not None
        if certificate is None or private_key is None:
            raise ValueError("Certificate or private key is None")

        # Convert to PEM format that MSAL expects
        key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

        return CertificateData(
            private_key=key_pem,
            thumbprint=certificate.fingerprint(hashes.SHA1()).hex(),  # noqa: S303 — MSAL certificate auth requires the SHA1 thumbprint per RFC 5280
        )
    except Exception as e:
        logger.error("Error loading certificate: %s", e)
        return None


def build_msal_app(
    *,
    client_id: str,
    directory_id: str,
    authority_host: str,
    auth_method: str = MicrosoftAuthMethod.CLIENT_SECRET.value,
    client_secret: str | None = None,
    private_key_b64: str | None = None,
    certificate_password: str | None = None,
) -> msal.ConfidentialClientApplication:
    """Build the app-only MSAL client for a connector's credential.

    ``private_key_b64`` is the base64-encoded PFX bundle as stored on the
    credential, not a PEM key.

    Callers own presence checks on the client and directory ids. Validating
    them here would turn Teams' plain MSAL failure into a
    ``ConnectorValidationError``, which cancels the attempt and marks the
    credential invalid.
    """
    authority_url = f"{authority_host}/{directory_id}"

    if auth_method == MicrosoftAuthMethod.CERTIFICATE.value:
        logger.info("Using certificate authentication")
        if not private_key_b64 or not certificate_password:
            raise ConnectorValidationError(
                "Private key and certificate password are required for certificate authentication"
            )

        certificate_data = load_certificate_from_pfx(
            base64.b64decode(private_key_b64), certificate_password
        )
        if certificate_data is None:
            raise RuntimeError("Failed to load certificate")

        logger.info("Creating MSAL app with authority url %s", authority_url)
        return msal.ConfidentialClientApplication(
            authority=authority_url,
            client_id=client_id,
            client_credential=certificate_data.model_dump(),
        )

    if auth_method == MicrosoftAuthMethod.CLIENT_SECRET.value:
        logger.info("Using client secret authentication")
        return msal.ConfidentialClientApplication(
            authority=authority_url,
            client_id=client_id,
            client_credential=client_secret,
        )

    raise ConnectorValidationError(
        "Invalid authentication method or missing required credentials"
    )


def acquire_graph_token(
    msal_app: msal.ConfidentialClientApplication,
    graph_api_host: str,
) -> dict[str, Any]:
    """Acquire an app-only Graph token. Returns MSAL's raw response."""
    return msal_app.acquire_token_for_client(scopes=[f"{graph_api_host}/.default"])
