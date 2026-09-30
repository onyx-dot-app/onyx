"""Shared parsing for Microsoft Graph and MSAL failures."""

import json
import re
from collections.abc import Generator
from typing import Any, NoReturn

import requests
from pydantic import BaseModel, ConfigDict

from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    CredentialInvalidError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.connectors.microsoft_utils.graph_client import (
    is_permanent_refusal_status,
)

NO_ERROR_CODE = "<no code>"
MISSING_CREDENTIAL_CODE = "missing_credential"
INVALID_AUTHORITY_CODE = "invalid_authority"
INVALID_AUTH_METHOD_CODE = "invalid_auth_method"
INVALID_CERTIFICATE_CODE = "invalid_certificate"
TRANSIENT_OAUTH_CODES = frozenset({"temporarily_unavailable", "server_error"})
INVALID_REGISTRATION_CODES = frozenset({"unauthorized_client", "invalid_request"})
_MSAL_STATUS_RE = re.compile(r"HTTP (?:status|Error): (\d{3})")


class MicrosoftGraphErrorDetails(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: int | None
    code: str
    message: str


class MicrosoftGraphError(Exception):
    def __init__(self, status: int | None, code: str, message: str) -> None:
        self.status = status
        self.code = code
        super().__init__(f"Graph {status} {code}: {message}")

    @property
    def is_permanent_refusal(self) -> bool:
        return is_permanent_refusal_status(self.status)

    @property
    def fails_the_attempt(self) -> bool:
        return self.status is None or self.status in (401, 429) or self.status >= 500


class MicrosoftAuthError(Exception):
    def __init__(self, code: str, description: str) -> None:
        self.code = code
        super().__init__(f"{code}: {description}")


def _exception_chain(error: BaseException) -> Generator[BaseException, None, None]:
    current: BaseException | None = error
    while current is not None:
        yield current
        current = current.__cause__ or current.__context__


def is_msal_decode_error(error: BaseException) -> bool:
    return any(
        isinstance(wrapped, json.JSONDecodeError) for wrapped in _exception_chain(error)
    )


def msal_http_status(error: BaseException) -> int | None:
    for wrapped in _exception_chain(error):
        if match := _MSAL_STATUS_RE.search(str(wrapped)):
            return int(match.group(1))
    return None


def parse_msal_error(error: BaseException) -> MicrosoftGraphErrorDetails:
    return MicrosoftGraphErrorDetails(
        status=msal_http_status(error),
        code=type(error).__name__,
        message=str(error),
    )


def parse_graph_error(error: Exception) -> MicrosoftGraphErrorDetails:
    response = error.response if isinstance(error, requests.RequestException) else None
    if response is None:
        return MicrosoftGraphErrorDetails(
            status=None,
            code=type(error).__name__,
            message=str(error),
        )

    try:
        payload: Any = response.json()
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        return MicrosoftGraphErrorDetails(
            status=response.status_code,
            code=NO_ERROR_CODE,
            message=response.text[:500],
        )

    detail = payload.get("error")
    if isinstance(detail, dict):
        code = detail.get("code") or NO_ERROR_CODE
        message = detail.get("message") or response.text
    else:
        code = detail or NO_ERROR_CODE
        message = payload.get("error_description") or response.text
    return MicrosoftGraphErrorDetails(
        status=response.status_code,
        code=str(code),
        message=str(message)[:500],
    )


def microsoft_error_from_exception(error: Exception) -> MicrosoftGraphError:
    details = (
        parse_graph_error(error)
        if isinstance(error, requests.RequestException)
        else parse_msal_error(error)
    )
    return MicrosoftGraphError(details.status, details.code, details.message)


def raise_for_auth_error(error: MicrosoftAuthError) -> NoReturn:
    if error.code in TRANSIENT_OAUTH_CODES:
        raise UnexpectedValidationError(
            "Microsoft's token endpoint is unavailable. Re-run the checks later."
        ) from error
    if error.code == MISSING_CREDENTIAL_CODE:
        raise CredentialInvalidError(
            "Microsoft credentials are incomplete; check all required fields."
        ) from error
    if error.code == INVALID_AUTHORITY_CODE:
        raise CredentialInvalidError(
            "Microsoft does not know this directory. Check the directory id and "
            "authority host."
        ) from error
    if error.code == INVALID_CERTIFICATE_CODE:
        raise CredentialInvalidError(
            "The PFX bundle could not be opened. Check the file and certificate "
            "password."
        ) from error
    if error.code == INVALID_AUTH_METHOD_CODE:
        raise CredentialInvalidError(
            "The Microsoft authentication method is invalid."
        ) from error
    if error.code == "invalid_client":
        raise CredentialInvalidError(
            "Microsoft rejected the client secret or certificate. It is wrong, "
            "expired, or belongs to a different app registration."
        ) from error
    if error.code in INVALID_REGISTRATION_CODES:
        raise CredentialInvalidError(
            "Microsoft rejected the app registration. Check the client id and "
            "directory id."
        ) from error
    raise CredentialInvalidError(
        f"Microsoft did not issue a token ({error.code})."
    ) from error


def raise_for_graph_error(
    error: MicrosoftGraphError,
    denied_message: str,
    *,
    remediation: str | None = None,
    permanent_refusal_message: str | None = None,
) -> NoReturn:
    if error.status == 401:
        raise CredentialExpiredError(
            f"Graph rejected the access token ({error.code})."
        ) from error
    if error.status == 403:
        detail = f"{denied_message} Graph reported `{error.code}`."
        if remediation:
            detail = f"{detail} {remediation}"
        raise InsufficientPermissionsError(detail) from error
    if error.is_permanent_refusal:
        raise ConnectorValidationError(
            permanent_refusal_message or denied_message
        ) from error
    if error.fails_the_attempt:
        raise UnexpectedValidationError(
            f"Graph is throttling or unreachable ({error.status} {error.code}). "
            "Re-run the checks later."
        ) from error
    raise UnexpectedValidationError(f"Unexpected Graph error: {error}") from error
