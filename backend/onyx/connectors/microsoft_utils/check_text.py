"""The row text of the Microsoft errors that ``graph_errors`` maps: the
sign-in refusals and the throttled, unreachable and unexpected answers.

A row has a short line (``summary``, 40 characters or fewer) and up to
three lines of description."""

from datetime import datetime, timezone

from onyx.connectors.microsoft_utils.models import MicrosoftAccountLabels
from onyx.connectors.models import CheckRowText

DEFAULT_ACCOUNT_LABELS = MicrosoftAccountLabels(
    client_id="Client ID",
    directory_id="Directory ID",
    client_secret="Client Secret",
    private_key="Private Key",
    certificate_password="Certificate Password",
)


def format_date(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y/%m/%d")


RATE_LIMITED_ROW = CheckRowText(
    summary="Microsoft is throttling requests",
    description="Microsoft limited the request rate.\nWait a few minutes, then re-run.",
)
UNREACHABLE_ROW = CheckRowText(
    summary="Cannot reach Microsoft",
    description=(
        "The request did not reach Microsoft, after retries.\nCheck that Onyx can "
        "reach Microsoft Graph, then re-run."
    ),
)
TOKEN_REJECTED_ROW = CheckRowText(
    summary="Microsoft rejected the app's token",
    description=(
        "Microsoft Graph refused the token the sign-in gave. (HTTP 401)\nCheck that "
        "the Graph API host matches the app's cloud, then re-run."
    ),
)


def unexpected_answer_row(request: str) -> CheckRowText:
    """``request`` names the call, such as "the site listing"."""
    return CheckRowText(
        summary="Unexpected answer from Microsoft",
        description=(
            f"Microsoft refused {request} in a way the check does not expect.\n"
            "Re-run the checks. If it repeats, send the error details to support."
        ),
    )


# Sign in to Microsoft: the same row for every Microsoft connector.
UNKNOWN_SIGN_IN_METHOD_ROW = CheckRowText(
    summary="Unknown sign-in method on the account",
    description=(
        "The account names a sign-in method other than client secret or "
        "certificate.\nCreate the account again with one of the two."
    ),
)
SIGN_IN_UNAVAILABLE_ROW = CheckRowText(
    summary="Microsoft sign-in is unavailable",
    description="Microsoft's sign-in service did not answer.\nRe-run the checks later.",
)
DIRECTORY_NOT_FOUND_ROW = CheckRowText(
    summary="Directory ID not found",
    description=(
        "Microsoft has no directory with this ID at the selected authority "
        "host.\nCheck the Directory ID, and that the authority host matches the "
        "app's cloud."
    ),
)
APP_NOT_FOUND_ROW = CheckRowText(
    summary="App registration not found",
    description=(
        "Microsoft did not find this client ID in this directory.\nCopy the "
        "Application (client) ID from the app registration's overview."
    ),
)


def no_token_row(code: str) -> CheckRowText:
    return CheckRowText(
        summary="Microsoft did not issue a token",
        description=(
            "Microsoft refused the token request for a reason the check does not "
            f"map ({code}).\nCheck the error details for the AADSTS code."
        ),
    )


def missing_field_row(
    labels: MicrosoftAccountLabels, *, certificate: bool
) -> CheckRowText:
    fields: str = (
        f"{labels.client_id}, {labels.directory_id}, {labels.private_key} and "
        f"{labels.certificate_password}"
        if certificate
        else f"{labels.client_id}, {labels.directory_id} and {labels.client_secret}"
    )
    return CheckRowText(
        summary="A required account field is empty",
        description=(
            f"The account is missing a field the sign-in needs.\nFill in {fields}."
        ),
    )


def certificate_unreadable_row(labels: MicrosoftAccountLabels) -> CheckRowText:
    return CheckRowText(
        summary="Certificate file does not open",
        description=(
            "The .pfx file or its password on this account is wrong.\nUpload the "
            f".pfx again as {labels.private_key} and re-enter "
            f"{labels.certificate_password}."
        ),
    )


def credential_rejected_row(
    labels: MicrosoftAccountLabels,
    *,
    certificate: bool,
    certificate_not_after: datetime | None = None,
    secret_expired: bool = False,
) -> CheckRowText:
    """``certificate_not_after`` in the past, or ``secret_expired``, names the
    expiry as the cause."""
    if certificate:
        expired: bool = certificate_not_after is not None and (
            certificate_not_after < datetime.now(timezone.utc)
        )
        cause: str = (
            f"The certificate on this account expired on "
            f"{format_date(certificate_not_after)}."
            if expired and certificate_not_after is not None
            else "Microsoft refused the certificate on this account."
        )
        return CheckRowText(
            summary="Secret or certificate was rejected",
            description=(
                f"{cause}\nUpload a current certificate under Certificates & "
                "secrets in the app registration, then upload its .pfx as "
                f"{labels.private_key}."
            ),
        )
    cause = (
        "The client secret on this account has expired."
        if secret_expired
        else "Microsoft refused the secret on this account."
    )
    return CheckRowText(
        summary="Secret or certificate was rejected",
        description=(
            f"{cause}\nCreate a new secret under Certificates & secrets in the app "
            f"registration and paste its Value into {labels.client_secret}."
        ),
    )
