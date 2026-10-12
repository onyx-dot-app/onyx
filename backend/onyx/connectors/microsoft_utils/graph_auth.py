"""App-only Microsoft Entra authentication shared by the Microsoft connectors.

Connectors map their own credential field names onto :func:`build_msal_app`,
which takes explicit values so the package never has to know whether a field is
called ``sp_client_id`` or ``teams_client_id``.

Callers keep their own "app is not initialized" and "token acquisition failed"
guards, and they do not agree on the exception type. Raising
``ConnectorValidationError`` cancels the index attempt and counts toward the
threshold that marks a credential invalid, so it is not interchangeable with
``RuntimeError``.
"""

import base64
from dataclasses import dataclass
from enum import Enum
from typing import Any, assert_never

import msal
import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from msal.exceptions import MsalServiceError
from office365.runtime.auth.token_response import TokenResponse
from pydantic import BaseModel

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.microsoft_utils.graph_errors import (
    INVALID_AUTH_METHOD_CODE,
    INVALID_AUTHORITY_CODE,
    INVALID_CERTIFICATE_CODE,
    MISSING_CREDENTIAL_CODE,
    MicrosoftAuthError,
    is_msal_decode_error,
    microsoft_error_from_exception,
    msal_http_status,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


class MicrosoftAuthMethod(Enum):
    CLIENT_SECRET = "client_secret"
    CERTIFICATE = "certificate"

    @property
    def supports_sharepoint_rest(self) -> bool:
        """SharePoint's REST and CSOM surface accepts an app-only token only
        when it came from a certificate. A client-secret token gets Access
        Denied whatever permissions are granted.
        https://learn.microsoft.com/en-us/sharepoint/dev/solution-guidance/security-apponly-azuread
        """
        return self is MicrosoftAuthMethod.CERTIFICATE

    @classmethod
    def parse(cls, value: str | None) -> "MicrosoftAuthMethod":
        """Parse a credential's ``authentication_method`` field.

        A missing or empty field means client secret, which is what every
        credential created before certificates existed carries.
        """
        if not value:
            return cls.CLIENT_SECRET
        try:
            return cls(value)
        except ValueError:
            expected = ", ".join(method.value for method in cls)
            raise ConnectorValidationError(
                f"Unknown authentication method {value!r}. Expected one of: {expected}."
            ) from None


@dataclass(frozen=True)
class MicrosoftAuthContext:
    """An MSAL client together with the credential type behind it, since the
    method decides which Microsoft surfaces the token may be sent to."""

    app: msal.ConfidentialClientApplication
    method: MicrosoftAuthMethod


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
            thumbprint=certificate.fingerprint(hashes.SHA1()).hex(),  # noqa: S303 MSAL certificate auth requires the SHA1 thumbprint per RFC 5280
        )
    except Exception as e:
        logger.error("Error loading certificate: %s", e)
        return None


def build_msal_app(
    *,
    client_id: str,
    directory_id: str,
    authority_host: str,
    auth_method: MicrosoftAuthMethod = MicrosoftAuthMethod.CLIENT_SECRET,
    client_secret: str | None = None,
    private_key_b64: str | None = None,
    certificate_password: str | None = None,
) -> MicrosoftAuthContext:
    """Build the app-only MSAL client for a connector's credential.

    ``private_key_b64`` is the base64-encoded PFX bundle as stored on the
    credential, not a PEM key. A connector whose credential carries a method
    string parses it with :meth:`MicrosoftAuthMethod.parse` first.

    Callers own presence checks on the ids. Validating them here would give
    every caller SharePoint's ``ConnectorValidationError``, which cancels the
    index attempt, where Teams surfaces an ordinary failure instead.
    """
    authority_url = f"{authority_host}/{directory_id}"

    if auth_method is MicrosoftAuthMethod.CERTIFICATE:
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
        return MicrosoftAuthContext(
            app=msal.ConfidentialClientApplication(
                authority=authority_url,
                client_id=client_id,
                client_credential=certificate_data.model_dump(),
            ),
            method=MicrosoftAuthMethod.CERTIFICATE,
        )

    if auth_method is MicrosoftAuthMethod.CLIENT_SECRET:
        logger.info("Using client secret authentication")
        return MicrosoftAuthContext(
            app=msal.ConfidentialClientApplication(
                authority=authority_url,
                client_id=client_id,
                client_credential=client_secret,
            ),
            method=MicrosoftAuthMethod.CLIENT_SECRET,
        )

    assert_never(auth_method)


def acquire_graph_token(
    msal_app: msal.ConfidentialClientApplication,
    graph_api_host: str,
) -> dict[str, Any]:
    """Acquire an app-only Graph token. Returns MSAL's raw response."""
    return msal_app.acquire_token_for_client(scopes=[f"{graph_api_host}/.default"])


def build_graph_auth_context(
    *,
    client_id: str | None,
    directory_id: str | None,
    authority_host: str,
    auth_method_value: str | None,
    client_secret: str | None,
    private_key_b64: str | None,
    certificate_password: str | None,
) -> MicrosoftAuthContext:
    try:
        auth_method = MicrosoftAuthMethod.parse(auth_method_value)
    except ConnectorValidationError as error:
        raise MicrosoftAuthError(INVALID_AUTH_METHOD_CODE, str(error)) from error

    required = [client_id, directory_id]
    if auth_method is MicrosoftAuthMethod.CLIENT_SECRET:
        required.append(client_secret)
    else:
        required.extend((private_key_b64, certificate_password))
    if any(not str(value or "").strip() for value in required):
        raise MicrosoftAuthError(
            MISSING_CREDENTIAL_CODE, "one or more required fields are missing"
        )

    if auth_method is MicrosoftAuthMethod.CERTIFICATE:
        try:
            base64.b64decode(private_key_b64 or "", validate=True)
        except ValueError as error:
            raise MicrosoftAuthError(INVALID_CERTIFICATE_CODE, str(error)) from error

    try:
        return build_msal_app(
            client_id=client_id or "",
            directory_id=directory_id or "",
            authority_host=authority_host,
            auth_method=auth_method,
            client_secret=client_secret,
            private_key_b64=private_key_b64,
            certificate_password=certificate_password,
        )
    except ValueError as error:
        status = msal_http_status(error)
        if (
            status == 429
            or status is not None
            and status >= 500
            or is_msal_decode_error(error)
        ):
            raise microsoft_error_from_exception(error) from error
        raise MicrosoftAuthError(INVALID_AUTHORITY_CODE, str(error)) from error
    except RuntimeError as error:
        raise MicrosoftAuthError(INVALID_CERTIFICATE_CODE, str(error)) from error
    except (MsalServiceError, requests.RequestException) as error:
        raise microsoft_error_from_exception(error) from error


def acquire_graph_token_response(
    auth_context: MicrosoftAuthContext,
    graph_api_host: str,
) -> dict[str, Any]:
    try:
        response = acquire_graph_token(auth_context.app, graph_api_host)
    except (MsalServiceError, ValueError, requests.RequestException) as error:
        raise microsoft_error_from_exception(error) from error
    if "access_token" not in response:
        raise MicrosoftAuthError(
            str(response.get("error") or "unknown_error"),
            str(response.get("error_description") or ""),
        )
    return response


def acquire_token_for_rest(
    msal_app: msal.ConfidentialClientApplication,
    sp_tenant_domain: str,
    sharepoint_domain_suffix: str,
) -> TokenResponse:
    """An app-only token for the tenant's SharePoint REST surface. SharePoint
    honors it only when the app signed in with a certificate."""
    token = msal_app.acquire_token_for_client(
        scopes=[f"https://{sp_tenant_domain}.{sharepoint_domain_suffix}/.default"]
    )
    return TokenResponse.from_json(token)
