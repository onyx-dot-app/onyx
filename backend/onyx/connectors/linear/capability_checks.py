"""Named indexing checks for Linear, composed from the gateway's operations.

Indexing needs a credential Linear accepts and, when the connector is scoped,
teams and projects Linear answers for. The permission sync checks build on the
same helpers from EE.

Linear hides a misspelled team or project and a private one the connected
user is not in the same way, so the not-found rows name both causes.
"""

from collections.abc import Callable
from enum import Enum
from typing import NoReturn, TypeVar

from onyx.connectors.capability_checks.form_state import FormState
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CheckOutput,
    CheckRowText,
    CredentialCapability,
    form_config,
    sign_in_timeout_text,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    CredentialInvalidError,
    InconclusiveValidationError,
    RateLimitedValidationError,
    TimedOutValidationError,
    UnexpectedValidationError,
    UnreachableValidationError,
)
from onyx.connectors.linear.config import LinearConnectorConfig
from onyx.connectors.linear.models import LinearViewer
from onyx.connectors.linear.scope import (
    issue_filter,
    missing_projects,
    missing_team_keys,
    normalize_team_keys,
    project_filter,
    project_scope,
    scope_error,
)
from onyx.connectors.linear.source_operations import (
    ACCESS_TOKEN,
    API_KEY,
    LinearApiError,
    LinearAuthError,
    LinearGraphQLError,
    LinearPagingError,
    LinearRateLimitError,
    LinearSourceOperations,
    LinearTokenLockError,
    LinearTokenRefreshError,
    LinearUnreachableError,
)
from onyx.connectors.models import ConnectorMissingCredentialError

T = TypeVar("T")

DOCS_LINK: str = "https://docs.onyx.app/admins/connectors/official/linear"
PROBE_PAGE_SIZE: int = 1
SIGN_IN_CHECK_ID: str = "linear_token"
ISSUES_CHECK_ID: str = "linear_issues"
_TEAMS_CHECK_ID: str = "linear_teams"
_PROJECTS_CHECK_ID: str = "linear_projects"
# check_id to the checks it runs after. A scope check that does not apply
# (no teams or no projects selected) does not stop the issues check.
_DEPENDS_ON: dict[str, tuple[str, ...]] = {
    _TEAMS_CHECK_ID: (SIGN_IN_CHECK_ID,),
    _PROJECTS_CHECK_ID: (SIGN_IN_CHECK_ID,),
    ISSUES_CHECK_ID: (SIGN_IN_CHECK_ID, _TEAMS_CHECK_ID, _PROJECTS_CHECK_ID),
}
_MAX_SUMMARY_CHARS: int = 40
# A refused renewal: the refresh token is spent, revoked or expired.
_REFRESH_REFUSED_STATUSES: frozenset[int] = frozenset({400, 401})


class _CredentialKind(str, Enum):
    API_KEY = "api_key"
    OAUTH = "oauth"


def _credential_kind(context: CapabilityCheckContext) -> _CredentialKind | None:
    if API_KEY in context.credential_json:
        return _CredentialKind.API_KEY
    if ACCESS_TOKEN in context.credential_json:
        return _CredentialKind.OAUTH
    return None


def _new_credential_line(context: CapabilityCheckContext) -> str:
    if _credential_kind(context) == _CredentialKind.OAUTH:
        return "Reconnect the account through Linear."
    return (
        "Create a new personal API key in Linear's settings, then paste it in "
        "the account's API Token."
    )


def member_need(context: CapabilityCheckContext) -> str:
    """The line that says what the credential needs, for its kind, to read
    the whole workspace: a workspace member rather than a guest."""
    if _credential_kind(context) == _CredentialKind.OAUTH:
        return "Reconnect through Linear as a workspace member, not a guest."
    return "Create the key as a workspace member, not a guest."


def gateway_from_context(context: CapabilityCheckContext) -> LinearSourceOperations:
    if not isinstance(context.source_operations, LinearSourceOperations):
        raise TypeError(
            "Bug: the runner constructs the registered gateway for migrated sources."
        )
    return context.source_operations


def config_from_context(context: CapabilityCheckContext) -> LinearConnectorConfig:
    return form_config(context, LinearConnectorConfig)


_TIMEOUT_TEXT = CheckRowText(
    summary="Timed out",
    description="The check ran past its time limit.\nRe-run the checks later.",
)
_SIGN_IN_TIMEOUT_TEXT = sign_in_timeout_text("Linear")


def _raise_for_linear_error(
    error: Exception, context: CapabilityCheckContext, failed: str, sign_in: bool
) -> NoReturn:
    """Maps a gateway error onto the validation-exception family. ``failed``
    leads the message of an error the check cannot word better."""
    if isinstance(error, LinearRateLimitError):
        raise RateLimitedValidationError(
            "Linear's rate limit stopped the check. Run the checks again later.",
            summary="Rate limited by Linear",
            description=(
                "Linear's rate limit stopped the check before it could decide.\n"
                "Wait for the limit to reset, then re-run."
            ),
        ) from error
    if isinstance(error, LinearAuthError):
        raise CredentialInvalidError(
            "Linear refused the credential. Check the API key or reconnect.",
            summary="Linear rejected the credential",
            description=(
                "Linear rejected the API key or OAuth token.\n"
                f"{_new_credential_line(context)}"
            ),
        ) from error
    if (
        isinstance(error, LinearTokenRefreshError)
        and error.status_code in _REFRESH_REFUSED_STATUSES
    ):
        raise CredentialExpiredError(
            f"Linear refused to renew the OAuth token. Reconnect the account. {error}",
            summary="Linear sign-in expired",
            description=(
                "The OAuth token expired and Linear refused to renew it.\n"
                "Reconnect the account through Linear."
            ),
        ) from error
    if isinstance(error, ConnectorMissingCredentialError):
        raise CredentialInvalidError(
            "The credential holds no Linear API key or OAuth token.",
            summary="No credential saved in the account",
            description=(
                "The account holds no API key or OAuth token.\n"
                f"{_new_credential_line(context)}"
            ),
        ) from error
    if isinstance(error, LinearTokenLockError):
        raise InconclusiveValidationError(
            f"{failed} {error}",
            summary="Token refresh is busy elsewhere",
            description=(
                "Another task holds the lock that renews this OAuth token.\n"
                "Wait a few minutes, then re-run."
            ),
        ) from error
    if isinstance(error, LinearUnreachableError) and error.timed_out:
        row: CheckRowText = _SIGN_IN_TIMEOUT_TEXT if sign_in else _TIMEOUT_TEXT
        raise TimedOutValidationError(
            f"Linear did not answer in time: {error}",
            summary=row.summary,
            description=row.description,
        ) from error
    if isinstance(error, LinearUnreachableError):
        raise UnreachableValidationError(
            f"Onyx cannot connect to Linear: {error}",
            summary="Cannot reach Linear",
            description=(
                "The request failed before Linear answered, after retries.\n"
                "Re-run the checks."
            ),
        ) from error
    if isinstance(error, LinearGraphQLError):
        raise UnexpectedValidationError(
            f"{failed} {error}",
            summary="Linear rejected the query",
            description=(
                "Linear returned errors for the query.\nRe-run the checks. If it "
                "repeats, share the error details with support."
            ),
        ) from error
    if isinstance(error, LinearPagingError):
        raise UnexpectedValidationError(
            f"{failed} {error}",
            summary="Linear paging stopped advancing",
            description=(
                "Linear returned the same page twice.\nRe-run the checks. If it "
                "repeats, share the error details with support."
            ),
        ) from error
    raise UnexpectedValidationError(
        f"{failed} {error}",
        summary="Unexpected response from Linear",
        description=(
            "Linear answered with an error this check does not expect.\nRe-run "
            "the checks. If it repeats, share the error details with support."
        ),
    ) from error


def probe(
    action: Callable[[], T],
    failed: str,
    context: CapabilityCheckContext,
    *,
    sign_in: bool = False,
) -> T:
    try:
        return action()
    except (
        LinearApiError,
        LinearPagingError,
        LinearTokenLockError,
        LinearUnreachableError,
        ConnectorMissingCredentialError,
    ) as error:
        _raise_for_linear_error(error, context, failed, sign_in)


def _fit(line: str, fallback: str) -> str:
    return line if len(line) <= _MAX_SUMMARY_CHARS else fallback


def _find_result(
    selected: list[str],
    missing: list[str],
    noun: str,
    hidden_line: str,
    message: str,
) -> CheckOutput:
    """A Find of selected entries: all found passes, some missing is a
    partial result the checks after it run on, none found FAILS."""
    if not missing:
        return CheckOutput(
            summary=(
                _fit(f"Found {noun} {selected[0]}", f"Found the selected {noun}")
                if len(selected) == 1
                else f"Found all {len(selected)} {noun}s"
            )
        )
    if len(missing) == len(selected):
        raise ConnectorValidationError(
            message,
            summary=f"No selected {noun} found",
            description=(
                f"None of the selected {noun}s is visible to this account.\n"
                f"{hidden_line}"
            ),
        )
    label: str = noun.capitalize() if len(missing) == 1 else f"{noun.capitalize()}s"
    return CheckOutput(
        summary=_fit(
            f"{label} not found: {', '.join(missing)}",
            f"{len(missing)} of {len(selected)} {noun}s not found",
        ),
        description=f"{hidden_line}\nNot found: {', '.join(missing)}.",
        partial=True,
    )


class _LinearCheck(CapabilityCheck[LinearConnectorConfig]):
    def __init__(
        self,
        *,
        check_id: str,
        display_name: str,
        remediation: str,
        requires_connector_config: bool = False,
        fails_when_unreachable: bool = False,
        timeout_text: CheckRowText = _TIMEOUT_TEXT,
    ) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id=check_id,
            display_name=display_name,
            depends_on=_DEPENDS_ON.get(check_id, ()),
            requires_connector_instance=False,
            requires_connector_config=requires_connector_config,
            remediation=remediation,
            docs_link=DOCS_LINK,
            fails_when_unreachable=fails_when_unreachable,
            timeout_text=timeout_text,
        )


class _TokenCheck(_LinearCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id=SIGN_IN_CHECK_ID,
            display_name="Sign in to Linear",
            remediation="Check the API key, or reconnect through OAuth.",
            fails_when_unreachable=True,
            timeout_text=_SIGN_IN_TIMEOUT_TEXT,
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        viewer: LinearViewer = probe(
            gateway_from_context(context).get_viewer,
            "Linear did not answer for the token.",
            context,
            sign_in=True,
        )
        if viewer.email is None:
            return CheckOutput(summary="Signed in to Linear")
        return CheckOutput(summary=f"Signed in as {viewer.email}")


class _TeamsCheck(_LinearCheck):
    config_class = LinearConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            check_id=_TEAMS_CHECK_ID,
            display_name="Find selected teams",
            requires_connector_config=True,
            remediation=(
                "Check each team key, or connect as a member of the team if it is private."
            ),
        )

    def applies(self, form_state: FormState[LinearConnectorConfig]) -> bool:
        return bool(form_state.config.team_keys)

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        keys: list[str] = normalize_team_keys(config_from_context(context).team_keys)
        missing: list[str] = probe(
            lambda: missing_team_keys(gateway_from_context(context), keys),
            "The configured teams could not be checked.",
            context,
        )
        return _find_result(
            keys,
            missing,
            "team",
            "Linear hides a misspelled key and a private team the connected "
            "user is not in the same way.",
            scope_error(missing, []).message,
        )


class _ProjectsCheck(_LinearCheck):
    config_class = LinearConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            check_id=_PROJECTS_CHECK_ID,
            display_name="Find selected projects",
            requires_connector_config=True,
            remediation=(
                "Check each project name or URL, or connect as a member of the "
                "project's team if it is private."
            ),
        )

    def applies(self, form_state: FormState[LinearConnectorConfig]) -> bool:
        return bool(form_state.config.projects)

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        names, slug_ids = project_scope(config_from_context(context).projects)
        missing: list[str] = probe(
            lambda: missing_projects(gateway_from_context(context), names, slug_ids),
            "The configured projects could not be checked.",
            context,
        )
        return _find_result(
            sorted([*names, *slug_ids]),
            missing,
            "project",
            "Linear hides a misspelled project and one in a private team the "
            "connected user is not in the same way.",
            scope_error([], missing).message,
        )


def scoped_issue_filter(context: CapabilityCheckContext) -> dict[str, object]:
    config: LinearConnectorConfig = config_from_context(context)
    names, slug_ids = project_scope(config.projects)
    return issue_filter(
        normalize_team_keys(config.team_keys), project_filter(names, slug_ids)
    )


class _IssuesCheck(_LinearCheck):
    """Reads the first issue in scope. No issue at all FAILS: the connector
    would index nothing."""

    config_class = LinearConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            check_id=ISSUES_CHECK_ID,
            display_name="Sample issues",
            remediation="Grant the credential read access to issues.",
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        pages = gateway_from_context(context).iterate_issues(
            issue_filter=scoped_issue_filter(context), page_size=PROBE_PAGE_SIZE
        )
        issues = probe(
            lambda: next(pages, []), "The credential cannot read issues.", context
        )
        if issues:
            return CheckOutput(summary=f"Read issue {issues[0]['identifier']}")
        config: LinearConnectorConfig = config_from_context(context)
        if config.team_keys or config.projects:
            raise ConnectorValidationError(
                "Linear returned no issue for the configured teams and projects, "
                "so the connector would index nothing.",
                summary="No issues in the selected scope",
                description="No issue matches the selected teams and projects.",
            )
        raise ConnectorValidationError(
            "Linear returned no issue the connected user can see, so the "
            "connector would index nothing.",
            summary="No issues in the selected scope",
            description="The connected user sees no issue in Linear.",
        )


def build_linear_indexing_checks() -> list[CapabilityCheck]:
    return [_TokenCheck(), _TeamsCheck(), _ProjectsCheck(), _IssuesCheck()]
