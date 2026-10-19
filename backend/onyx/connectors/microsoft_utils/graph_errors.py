"""Shared parsing for Microsoft Graph and MSAL failures."""

import json
import re
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any, NoReturn

import requests
from pydantic import BaseModel, ConfigDict

from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    CredentialInvalidError,
    InsufficientPermissionsError,
    RateLimitedValidationError,
    SourceApiError,
    UnexpectedValidationError,
    UnreachableValidationError,
    ValidationError,
)
from onyx.connectors.microsoft_utils.check_text import (
    APP_NOT_FOUND_ROW,
    DEFAULT_ACCOUNT_LABELS,
    DIRECTORY_NOT_FOUND_ROW,
    RATE_LIMITED_ROW,
    SIGN_IN_REFUSED_ROW,
    SIGN_IN_UNAVAILABLE_ROW,
    SIGN_IN_UNEXPECTED_ROW,
    SIGN_IN_UNREACHABLE_ROW,
    TOKEN_REJECTED_ROW,
    UNKNOWN_SIGN_IN_METHOD_ROW,
    UNREACHABLE_ROW,
    certificate_unreadable_row,
    credential_rejected_row,
    missing_field_row,
    no_token_row,
    unexpected_answer_row,
)
from onyx.connectors.microsoft_utils.graph_client import (
    TRANSIENT_TRANSPORT_EXCEPTIONS,
    is_permanent_refusal_status,
)
from onyx.connectors.microsoft_utils.models import (
    MicrosoftAccountLabels,
    MicrosoftRowText,
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


class MicrosoftGraphError(SourceApiError):
    """A Graph, SharePoint REST or token endpoint refusal. ``status`` is None
    for a failure with no answer, such as a dropped connection."""

    def __init__(
        self,
        status: int | None,
        code: str,
        message: str,
        *,
        method: str | None = None,
        url: str | None = None,
        body: str | None = None,
    ) -> None:
        super().__init__(
            f"Graph {status} {code}: {message}",
            status_code=status,
            method=method,
            url=url,
            body=body,
        )
        self.status = status
        self.code = code

    @property
    def is_permanent_refusal(self) -> bool:
        return is_permanent_refusal_status(self.status)

    @property
    def fails_the_attempt(self) -> bool:
        return self.status is None or self.status in (401, 429) or self.status >= 500


class MicrosoftAuthError(Exception):
    """Entra refused to sign the app in. ``certificate`` marks a certificate
    account; ``certificate_not_after`` is its certificate's end date, when
    the certificate opened."""

    def __init__(
        self,
        code: str,
        description: str,
        *,
        certificate: bool = False,
        certificate_not_after: datetime | None = None,
    ) -> None:
        self.code = code
        self.certificate = certificate
        self.certificate_not_after = certificate_not_after
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
    """The error with its status and code, and, when it carries an answer,
    the request and response body for Error Details."""
    details = (
        parse_graph_error(error)
        if isinstance(error, requests.RequestException)
        else parse_msal_error(error)
    )
    response = error.response if isinstance(error, requests.RequestException) else None
    if response is None:
        return MicrosoftGraphError(details.status, details.code, details.message)
    request = response.request
    return MicrosoftGraphError(
        details.status,
        details.code,
        details.message,
        method=request.method if request is not None else None,
        url=response.url or (request.url if request is not None else None),
        body=response.text or None,
    )


@contextmanager
def raise_microsoft_errors() -> Iterator[None]:
    """Raises a Graph or SharePoint refusal as ``MicrosoftGraphError``, which
    carries the status without the SDK. The office365 SDK's
    ``ClientRequestException`` is a ``RequestException``. A decode error is
    the empty or non-JSON body Graph answers under load."""
    try:
        yield
    except (requests.RequestException, json.JSONDecodeError) as error:
        raise microsoft_error_from_exception(error) from error


# Entra's code for an expired client secret.
_EXPIRED_SECRET_CODE = "AADSTS7000222"


def _raise_with_row(
    error_class: type[ValidationError],
    message: str,
    row: MicrosoftRowText | None,
    cause: Exception,
) -> NoReturn:
    raise error_class(
        message,
        summary=row.summary if row else None,
        description=row.description if row else None,
    ) from cause


def raise_for_auth_error(
    error: MicrosoftAuthError,
    labels: MicrosoftAccountLabels = DEFAULT_ACCOUNT_LABELS,
) -> NoReturn:
    """Maps an Entra sign-in refusal onto the validation family, with the
    sign-in row's text. ``labels`` name the account's fields."""
    if error.code in TRANSIENT_OAUTH_CODES:
        _raise_with_row(
            UnexpectedValidationError,
            "Microsoft's token endpoint is unavailable. Re-run the checks later.",
            SIGN_IN_UNAVAILABLE_ROW,
            error,
        )
    if error.code == MISSING_CREDENTIAL_CODE:
        _raise_with_row(
            CredentialInvalidError,
            "Microsoft credentials are incomplete; check all required fields.",
            missing_field_row(labels, certificate=error.certificate),
            error,
        )
    if error.code == INVALID_AUTHORITY_CODE:
        _raise_with_row(
            CredentialInvalidError,
            "Microsoft does not know this directory. Check the directory id and "
            "authority host.",
            DIRECTORY_NOT_FOUND_ROW,
            error,
        )
    if error.code == INVALID_CERTIFICATE_CODE:
        _raise_with_row(
            CredentialInvalidError,
            "The PFX bundle could not be opened. Check the file and certificate "
            "password.",
            certificate_unreadable_row(labels),
            error,
        )
    if error.code == INVALID_AUTH_METHOD_CODE:
        _raise_with_row(
            CredentialInvalidError,
            "The Microsoft authentication method is invalid.",
            UNKNOWN_SIGN_IN_METHOD_ROW,
            error,
        )
    if error.code == "invalid_client":
        _raise_with_row(
            CredentialInvalidError,
            "Microsoft rejected the client secret or certificate. It is wrong, "
            "expired, or belongs to a different app registration.",
            credential_rejected_row(
                labels,
                certificate=error.certificate,
                certificate_not_after=error.certificate_not_after,
                secret_expired=_EXPIRED_SECRET_CODE in str(error),
            ),
            error,
        )
    if error.code in INVALID_REGISTRATION_CODES:
        _raise_with_row(
            CredentialInvalidError,
            "Microsoft rejected the app registration. Check the client id and "
            "directory id.",
            APP_NOT_FOUND_ROW,
            error,
        )
    _raise_with_row(
        CredentialInvalidError,
        f"Microsoft did not issue a token ({error.code}).",
        no_token_row(error.code),
        error,
    )


def _is_transport_failure(error: MicrosoftGraphError) -> bool:
    """No answer came back: the connection failed or timed out, after
    retries."""
    return error.status is None and any(
        isinstance(wrapped, TRANSIENT_TRANSPORT_EXCEPTIONS)
        for wrapped in _exception_chain(error)
    )


def raise_for_sign_in_error(error: MicrosoftGraphError) -> NoReturn:
    """Maps a failed token request that Entra did not answer with an OAuth
    error: throttled, unreachable, down, or refused outright."""
    if error.status == 429:
        _raise_with_row(
            RateLimitedValidationError,
            f"Microsoft's token endpoint is throttling ({error.code}). Re-run the "
            "checks later.",
            RATE_LIMITED_ROW,
            error,
        )
    if _is_transport_failure(error):
        _raise_with_row(
            UnreachableValidationError,
            f"Onyx cannot reach Microsoft's token endpoint ({error.code}).",
            SIGN_IN_UNREACHABLE_ROW,
            error,
        )
    if error.status is not None and error.status >= 500:
        _raise_with_row(
            UnexpectedValidationError,
            f"Microsoft's token endpoint is unavailable ({error.status} "
            f"{error.code}). Re-run the checks later.",
            SIGN_IN_UNAVAILABLE_ROW,
            error,
        )
    if error.status is not None and error.status >= 400:
        _raise_with_row(
            CredentialInvalidError,
            f"Microsoft refused the token request. Graph reported `{error.code}`.",
            SIGN_IN_REFUSED_ROW,
            error,
        )
    _raise_with_row(
        UnexpectedValidationError,
        f"Microsoft's token endpoint answered unexpectedly ({error.status} "
        f"{error.code}).",
        SIGN_IN_UNEXPECTED_ROW,
        error,
    )


def raise_for_graph_error(
    error: MicrosoftGraphError,
    denied_message: str,
    *,
    remediation: str | None = None,
    permanent_refusal_message: str | None = None,
    denied_row: MicrosoftRowText | None = None,
    not_found_row: MicrosoftRowText | None = None,
    request: str = "the request",
) -> NoReturn:
    """Maps a Graph or SharePoint REST refusal onto the validation family.
    ``denied_row`` is the row of a 403, ``not_found_row`` of a 404 or 423;
    ``request`` names the call in the unexpected-answer row."""
    if error.status == 401:
        _raise_with_row(
            CredentialExpiredError,
            f"Graph rejected the access token ({error.code}).",
            TOKEN_REJECTED_ROW,
            error,
        )
    if error.status == 403:
        detail = f"{denied_message} Graph reported `{error.code}`."
        if remediation:
            detail = f"{detail} {remediation}"
        _raise_with_row(InsufficientPermissionsError, detail, denied_row, error)
    if error.is_permanent_refusal:
        _raise_with_row(
            ConnectorValidationError,
            permanent_refusal_message or denied_message,
            not_found_row,
            error,
        )
    if error.status == 429:
        _raise_with_row(
            RateLimitedValidationError,
            f"Graph is throttling ({error.status} {error.code}). Re-run the checks "
            "later.",
            RATE_LIMITED_ROW,
            error,
        )
    if _is_transport_failure(error):
        _raise_with_row(
            UnreachableValidationError,
            f"Graph is unreachable ({error.code}). Re-run the checks later.",
            UNREACHABLE_ROW,
            error,
        )
    if error.fails_the_attempt:
        _raise_with_row(
            UnexpectedValidationError,
            f"Graph answered with an error ({error.status} {error.code}). Re-run "
            "the checks later.",
            unexpected_answer_row(request),
            error,
        )
    _raise_with_row(
        UnexpectedValidationError,
        f"Unexpected Graph error: {error}",
        unexpected_answer_row(request),
        error,
    )
