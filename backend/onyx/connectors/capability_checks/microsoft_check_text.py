"""The Microsoft text only capability checks use: the sign-in probe every
Microsoft connector's first check runs, its rows, and the lines that say
which grant an app registration needs."""

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import NoReturn

from onyx.connectors.capability_checks.models import MicrosoftSignIn
from onyx.connectors.exceptions import (
    CredentialInvalidError,
    RateLimitedValidationError,
    UnexpectedValidationError,
    UnreachableValidationError,
)
from onyx.connectors.microsoft_utils.check_text import (
    RATE_LIMITED_ROW,
    SIGN_IN_UNAVAILABLE_ROW,
    format_date,
)
from onyx.connectors.microsoft_utils.graph_errors import (
    MicrosoftAuthError,
    MicrosoftGraphError,
    is_transport_failure,
    raise_for_auth_error,
    raise_with_row,
)
from onyx.connectors.microsoft_utils.models import (
    MicrosoftAccountLabels,
    MicrosoftTokenInfo,
)
from onyx.connectors.models import CheckRowText, fit_summary

GRAPH_API = "Microsoft Graph"
SHAREPOINT_API = "SharePoint API"
# A certificate this close to its end date gets a caveat on the sign-in row.
CERTIFICATE_EXPIRY_WARNING = timedelta(days=30)


def grant_line(permission: str, api: str = GRAPH_API) -> str:
    """The line that tells the admin which application permission to grant."""
    return (
        f"Grant `{permission}` ({api}, application) to the app registration and "
        "admin-consent it."
    )


ENTRA_GROUPS_DENIED_ROW = CheckRowText(
    summary="No permission to read Entra groups",
    description=(
        "The app cannot list the tenant's Entra groups.\n"
        + grant_line("GroupMember.Read.All")
    ),
)

SIGN_IN_UNEXPECTED_ROW = CheckRowText(
    summary="Unexpected answer from Microsoft sign-in",
    description=(
        "Microsoft's sign-in service answered in a way the check does not "
        "expect.\nRe-run the checks. If it repeats, send the error details to "
        "support."
    ),
)
SIGN_IN_UNREACHABLE_ROW = CheckRowText(
    summary="Cannot reach Microsoft sign-in",
    description=(
        "The sign-in request did not reach Microsoft, after retries.\nCheck that "
        "Onyx can reach the authority host, then re-run."
    ),
)
SIGN_IN_REFUSED_ROW = CheckRowText(
    summary="Microsoft refused the sign-in request",
    description=(
        "Microsoft's sign-in service refused the request.\nCheck the error "
        "details for the AADSTS code and fix what it names."
    ),
)


def raise_for_sign_in_error(error: MicrosoftGraphError) -> NoReturn:
    """Maps a failed token request that Entra did not answer with an OAuth
    error: throttled, unreachable, down, or refused outright."""
    if error.status == 429:
        raise_with_row(
            RateLimitedValidationError,
            f"Microsoft's token endpoint is throttling ({error.code}). Re-run the "
            "checks later.",
            RATE_LIMITED_ROW,
            error,
        )
    if is_transport_failure(error):
        raise_with_row(
            UnreachableValidationError,
            f"Onyx cannot reach Microsoft's token endpoint ({error.code}).",
            SIGN_IN_UNREACHABLE_ROW,
            error,
        )
    if error.status is not None and error.status >= 500:
        raise_with_row(
            UnexpectedValidationError,
            f"Microsoft's token endpoint is unavailable ({error.status} "
            f"{error.code}). Re-run the checks later.",
            SIGN_IN_UNAVAILABLE_ROW,
            error,
        )
    if error.status is not None and error.status >= 400:
        raise_with_row(
            CredentialInvalidError,
            f"Microsoft refused the token request. Graph reported `{error.code}`.",
            SIGN_IN_REFUSED_ROW,
            error,
        )
    raise_with_row(
        UnexpectedValidationError,
        f"Microsoft's token endpoint answered unexpectedly ({error.status} "
        f"{error.code}).",
        SIGN_IN_UNEXPECTED_ROW,
        error,
    )


def sign_in_text(
    token: MicrosoftTokenInfo, labels: MicrosoftAccountLabels
) -> MicrosoftSignIn:
    """The app's name from the token, and the certificate's end date. A
    certificate near its end date gets a caveat. A name too long for the
    summary is cut there and given in full in the description."""
    summary: str = "Signed in to Microsoft"
    lines: list[str] = []
    if token.app_name:
        summary = fit_summary("Signed in as ", token.app_name)
        if summary != f"Signed in as {token.app_name}":
            lines.append(f"App: {token.app_name}")
    elif token.app_id:
        summary = fit_summary("Signed in as app ", token.app_id)
        if summary != f"Signed in as app {token.app_id}":
            lines.append(f"App ID: {token.app_id}")
    not_after: datetime | None = token.certificate_not_after
    caveats: list[str] = []
    if not_after is not None:
        lines.append(f"Certificate valid until {format_date(not_after)}.")
        if not_after - datetime.now(timezone.utc) <= CERTIFICATE_EXPIRY_WARNING:
            caveats.append(
                f"The certificate expires on {format_date(not_after)}. Upload a "
                f"new .pfx as {labels.private_key} before then, or sign-in stops "
                "working."
            )
    return MicrosoftSignIn(
        summary=summary,
        description="\n".join(lines) or None,
        caveats=caveats,
    )


def sign_in(
    check_token: Callable[[], MicrosoftTokenInfo], labels: MicrosoftAccountLabels
) -> MicrosoftSignIn:
    """Signs in with ``check_token`` and returns the passing row's text.
    Raises the validation family with the sign-in row's text."""
    try:
        token: MicrosoftTokenInfo = check_token()
    except MicrosoftAuthError as error:
        raise_for_auth_error(error, labels)
    except MicrosoftGraphError as error:
        raise_for_sign_in_error(error)
    return sign_in_text(token, labels)
