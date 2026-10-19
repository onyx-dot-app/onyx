"""The row text the Microsoft connectors' capability checks share: the
sign-in rows, the throttled and unreachable rows, and the lines that say
which grant an app registration needs.

A check's row has a short line (``summary``, 40 characters or fewer) and up
to three lines of description. The connectors wrap these in their check
outputs and errors."""

from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, ConfigDict

from onyx.connectors.microsoft_utils.models import MicrosoftTokenInfo

GRAPH_API = "Microsoft Graph"
SHAREPOINT_API = "SharePoint API"
# A row's summary is this many characters or fewer.
MAX_SUMMARY_LENGTH = 40
# A certificate this close to its end date gets a caveat on the sign-in row.
CERTIFICATE_EXPIRY_WARNING = timedelta(days=30)


class MicrosoftRowText(BaseModel):
    """The row text of one outcome of a probe."""

    model_config = ConfigDict(frozen=True)

    summary: str
    description: str


class MicrosoftAccountLabels(BaseModel):
    """The names the connector form gives the account's fields, for lines
    that tell the admin which field to fix."""

    model_config = ConfigDict(frozen=True)

    client_id: str
    directory_id: str
    client_secret: str
    private_key: str
    certificate_password: str

    @classmethod
    def with_prefix(
        cls, prefix: str, *, private_key: str | None = None
    ) -> "MicrosoftAccountLabels":
        return cls(
            client_id=f"{prefix} Client ID",
            directory_id=f"{prefix} Directory ID",
            client_secret=f"{prefix} Client Secret",
            private_key=private_key or f"{prefix} Private Key",
            certificate_password=f"{prefix} Certificate Password",
        )


DEFAULT_ACCOUNT_LABELS = MicrosoftAccountLabels(
    client_id="Client ID",
    directory_id="Directory ID",
    client_secret="Client Secret",
    private_key="Private Key",
    certificate_password="Certificate Password",
)


def grant_line(permission: str, api: str = GRAPH_API) -> str:
    """The line that tells the admin which application permission to grant."""
    return (
        f"Grant `{permission}` ({api}, application) to the app registration and "
        "admin-consent it."
    )


def fit_line(prefix: str, name: str, suffix: str = "") -> str:
    """``prefix``, ``name`` and ``suffix``, with the name cut to fit a summary."""
    room: int = MAX_SUMMARY_LENGTH - len(prefix) - len(suffix)
    cut: str = name if len(name) <= room else name[: room - 1] + "\u2026"
    return f"{prefix}{cut}{suffix}"


def format_date(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y/%m/%d")


RATE_LIMITED_ROW = MicrosoftRowText(
    summary="Microsoft is throttling requests",
    description="Microsoft limited the request rate.\nWait a few minutes, then re-run.",
)
UNREACHABLE_ROW = MicrosoftRowText(
    summary="Cannot reach Microsoft",
    description=(
        "The request did not reach Microsoft, after retries.\nCheck that Onyx can "
        "reach Microsoft Graph, then re-run."
    ),
)
TOKEN_REJECTED_ROW = MicrosoftRowText(
    summary="Microsoft rejected the app's token",
    description=(
        "Microsoft Graph refused the token the sign-in gave. (HTTP 401)\nCheck that "
        "the Graph API host matches the app's cloud, then re-run."
    ),
)


def unexpected_answer_row(request: str) -> MicrosoftRowText:
    """``request`` names the call, such as "the site listing"."""
    return MicrosoftRowText(
        summary="Unexpected answer from Microsoft",
        description=(
            f"Microsoft refused {request} in a way the check does not expect.\n"
            "Re-run the checks. If it repeats, send the error details to support."
        ),
    )


# Sign in to Microsoft: the same row for every Microsoft connector.
UNKNOWN_SIGN_IN_METHOD_ROW = MicrosoftRowText(
    summary="Unknown sign-in method on the account",
    description=(
        "The account names a sign-in method other than client secret or "
        "certificate.\nCreate the account again with one of the two."
    ),
)
SIGN_IN_UNAVAILABLE_ROW = MicrosoftRowText(
    summary="Microsoft sign-in is unavailable",
    description="Microsoft's sign-in service did not answer.\nRe-run the checks later.",
)
SIGN_IN_UNEXPECTED_ROW = MicrosoftRowText(
    summary="Unexpected answer from Microsoft sign-in",
    description=(
        "Microsoft's sign-in service answered in a way the check does not "
        "expect.\nRe-run the checks. If it repeats, send the error details to "
        "support."
    ),
)
SIGN_IN_UNREACHABLE_ROW = MicrosoftRowText(
    summary="Cannot reach Microsoft sign-in",
    description=(
        "The sign-in request did not reach Microsoft, after retries.\nCheck that "
        "Onyx can reach the authority host, then re-run."
    ),
)
SIGN_IN_REFUSED_ROW = MicrosoftRowText(
    summary="Microsoft refused the sign-in request",
    description=(
        "Microsoft's sign-in service refused the request.\nCheck the error "
        "details for the AADSTS code and fix what it names."
    ),
)
DIRECTORY_NOT_FOUND_ROW = MicrosoftRowText(
    summary="Directory ID not found",
    description=(
        "Microsoft has no directory with this ID at the selected authority "
        "host.\nCheck the Directory ID, and that the authority host matches the "
        "app's cloud."
    ),
)
APP_NOT_FOUND_ROW = MicrosoftRowText(
    summary="App registration not found",
    description=(
        "Microsoft did not find this client ID in this directory.\nCopy the "
        "Application (client) ID from the app registration's overview."
    ),
)


def no_token_row(code: str) -> MicrosoftRowText:
    return MicrosoftRowText(
        summary="Microsoft did not issue a token",
        description=(
            "Microsoft refused the token request for a reason the check does not "
            f"map ({code}).\nCheck the error details for the AADSTS code."
        ),
    )


def missing_field_row(
    labels: MicrosoftAccountLabels, *, certificate: bool
) -> MicrosoftRowText:
    fields: str = (
        f"{labels.client_id}, {labels.directory_id}, {labels.private_key} and "
        f"{labels.certificate_password}"
        if certificate
        else f"{labels.client_id}, {labels.directory_id} and {labels.client_secret}"
    )
    return MicrosoftRowText(
        summary="A required account field is empty",
        description=(
            f"The account is missing a field the sign-in needs.\nFill in {fields}."
        ),
    )


def certificate_unreadable_row(labels: MicrosoftAccountLabels) -> MicrosoftRowText:
    return MicrosoftRowText(
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
) -> MicrosoftRowText:
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
        return MicrosoftRowText(
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
    return MicrosoftRowText(
        summary="Secret or certificate was rejected",
        description=(
            f"{cause}\nCreate a new secret under Certificates & secrets in the app "
            f"registration and paste its Value into {labels.client_secret}."
        ),
    )


class MicrosoftSignIn(BaseModel):
    """What a passing sign-in check shows: its line, and caveats."""

    summary: str
    description: str | None = None
    caveats: list[str] = []


def sign_in_text(
    token: MicrosoftTokenInfo, labels: MicrosoftAccountLabels
) -> MicrosoftSignIn:
    """The app's name from the token, and the certificate's end date. A
    certificate near its end date gets a caveat. A name too long for the
    summary is cut there and given in full in the description."""
    summary: str = "Signed in to Microsoft"
    lines: list[str] = []
    if token.app_name:
        summary = fit_line("Signed in as ", token.app_name)
        if summary != f"Signed in as {token.app_name}":
            lines.append(f"App: {token.app_name}")
    elif token.app_id:
        summary = fit_line("Signed in as app ", token.app_id)
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
