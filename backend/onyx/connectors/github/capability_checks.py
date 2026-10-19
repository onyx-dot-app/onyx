"""Capability checks for the GitHub connector.

The indexing checks register in ``registry.py``; the permission-sync and
group-sync checks register in the EE registry
(``ee/onyx/connectors/capability_checks.py``). Each check makes small probes
(one page, one pull request, one file, a few users) with the gateway
operations that its sync calls.

The credential is a personal access token: classic (OAuth scopes) or
fine-grained (repository permissions). GitHub answers 404, not 403, for a
private repository that the token cannot see, so a missing repository and a
missing grant look the same. The messages name both causes and, when GitHub
sends them, the scopes or permissions the endpoint accepts.

The repositories to index follow the connector: the listed repositories, or
every repository of the owner (an organization, else a user).
"""

from typing import NoReturn

import requests
from pydantic import BaseModel

from onyx.connectors.capability_checks.form_state import FormState
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CheckAdvisory,
    CheckOutput,
    CredentialCapability,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    CredentialInvalidError,
    InconclusiveValidationError,
    InsufficientPermissionsError,
    NothingToCheckError,
    RateLimitedValidationError,
    UnexpectedValidationError,
    UnreachableValidationError,
)
from onyx.connectors.github.config import GithubConnectorConfig
from onyx.connectors.github.connector import (
    is_cursor_pagination_required,
    is_indexable_path,
)
from onyx.connectors.github.models import (
    GitHubGitTree,
    GitHubIssue,
    GitHubPullRequest,
    GitHubRepository,
    GitHubTokenInfo,
    GitHubTokenKind,
)
from onyx.connectors.github.source_operations import (
    GitHubApiError,
    GitHubRateLimitError,
    GitHubSourceOperations,
)
from onyx.connectors.github.utils import parse_repository_names
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.source_operations import SourceOperations

_DOCS_LINK = "https://docs.onyx.app/admins/connectors/official/github"
_SSO_GUIDE_LINK = (
    "https://docs.github.com/en/enterprise-cloud@latest/authentication/"
    "authenticating-with-saml-single-sign-on/"
    "authorizing-a-personal-access-token-for-use-with-saml-single-sign-on"
)
_OWNER_FIELDS = frozenset({"repo_owner"})
_ERROR_DETAIL_CHARS = 300
# GitHub's text when a SAML organization has not authorized the token.
_SAML_TEXT = "saml enforcement"
_EMPTY_REPOSITORY_STATUS = 409
_PRIVATE_REPOSITORY_SCOPE = "repo"
# Repositories a branch check reads in all-repositories mode.
_SAMPLE_REPOSITORIES = 5
# Items a check lists to count them: one page.
_COUNT_LIMIT = 100

_TOKEN_ACCESS_HINT = (
    "Classic token: the `repo` scope reads private repositories. Fine-grained "
    "token: its resource owner must be the repository owner, and its repository "
    "access must include the repositories."
)

_AUTH_CHECK_ID = "github_auth"
_OWNER_CHECK_ID = "github_owner"
_REPOSITORY_CHECK_IDS = (
    "github_repositories_visible",
    "github_configured_repositories",
)
_COLLABORATORS_CHECK_ID = "github_repository_collaborators"
_MEMBERS_CHECK_ID = "github_organization_members"
# check_id to the checks it runs after, in run order. The two repository
# checks are alternatives: only one applies to a config.
_DEPENDS_ON: dict[str, tuple[str, ...]] = {
    "github_token_scopes": (_AUTH_CHECK_ID,),
    _OWNER_CHECK_ID: (_AUTH_CHECK_ID,),
    "github_repositories_visible": (_OWNER_CHECK_ID,),
    "github_configured_repositories": (_OWNER_CHECK_ID,),
    "github_branch": _REPOSITORY_CHECK_IDS,
    "github_pull_requests": _REPOSITORY_CHECK_IDS,
    "github_issues": _REPOSITORY_CHECK_IDS,
    "github_files": ("github_branch", *_REPOSITORY_CHECK_IDS),
    "github_repository_visibility": _REPOSITORY_CHECK_IDS,
    _COLLABORATORS_CHECK_ID: _REPOSITORY_CHECK_IDS,
    _MEMBERS_CHECK_ID: _REPOSITORY_CHECK_IDS,
    # Not the collaborators and members checks: one of them finds nothing to
    # test when the repositories are all private or all internal, and the
    # emails check still reads the users of the other.
    "github_user_emails": _REPOSITORY_CHECK_IDS,
}


class _RowText(BaseModel):
    """The row text of one outcome of a probe."""

    summary: str
    description: str


def _gateway(context: CapabilityCheckContext) -> GitHubSourceOperations:
    gateway: SourceOperations | None = context.source_operations
    if not isinstance(gateway, GitHubSourceOperations):
        raise TypeError(
            "Bug: The runner constructs the registered gateway for migrated sources."
        )
    return gateway


def _owner(config: GithubConnectorConfig) -> str:
    return config.repo_owner.strip()


def _detail(error: GitHubApiError) -> str:
    return (error.github_message or str(error))[:_ERROR_DETAIL_CHARS]


def _accepted_access(error: GitHubApiError) -> str:
    """What the endpoint accepts, as GitHub sent it in the headers."""
    if error.accepted_permissions:
        return (
            " The endpoint needs the fine-grained permission "
            f"`{error.accepted_permissions}`."
        )
    if error.accepted_scopes:
        return f" The endpoint accepts the classic scopes `{error.accepted_scopes}`."
    return ""


def _is_saml_denial(error: GitHubApiError) -> bool:
    return error.sso_required or _SAML_TEXT in (error.github_message or "").lower()


def _token_info(gateway: GitHubSourceOperations) -> GitHubTokenInfo | None:
    """The token's kind and scopes, or None when GitHub does not answer.
    github_auth reports why."""
    try:
        return gateway.get_token_info()
    except GitHubApiError:
        return None


def _need(
    context: CapabilityCheckContext, *, scope: str | None, permission: str
) -> str:
    """The line that says what the token needs, for its kind: a classic
    token's scope, a fine-grained token's permission."""
    token: GitHubTokenInfo | None = _token_info(_gateway(context))
    kind: GitHubTokenKind | None = token.kind if token is not None else None
    if kind == GitHubTokenKind.CLASSIC:
        return (
            f"Select the {scope} scope."
            if scope is not None
            else "Give the token's user access in GitHub."
        )
    if kind == GitHubTokenKind.FINE_GRAINED:
        return f"Give the token read access to {permission}."
    if scope is None:
        return f"Fine-grained token: give it read access to {permission}."
    return (
        f"Classic token: select the {scope} scope. Fine-grained token: give it "
        f"read access to {permission}."
    )


def _raise_for_api_error(
    error: GitHubApiError,
    *,
    denied: str,
    denied_row: _RowText | None = None,
    not_found: str | None = None,
    not_found_row: _RowText | None = None,
) -> NoReturn:
    """Maps a GitHub API error onto the validation-exception family.
    ``denied`` explains a 403 for this probe, ``not_found`` a 404; the rows
    are what the check's row shows for them."""
    status: int | None = error.status_code
    if isinstance(error, GitHubRateLimitError):
        kind: str = "secondary rate limit" if error.secondary else "rate limit"
        raise RateLimitedValidationError(
            f"GitHub's {kind} stopped the check. Run the checks again later.",
            summary="Rate limited by GitHub",
            description=(
                "GitHub's rate limit stopped the check before it could decide. "
                f"(HTTP {status})\nWait for the limit to reset, then re-run."
            ),
        ) from error
    if status == 401:
        raise CredentialExpiredError(
            "GitHub rejected the token (HTTP 401). The token is wrong, expired, "
            "or revoked. Create a new token.",
            summary="Token is invalid, expired or revoked",
            description=(
                "GitHub rejected the token. (HTTP 401)\nCreate a new token under "
                "GitHub Settings > Developer settings > Personal access tokens, "
                "then paste it in the account's API Token."
            ),
        ) from error
    if status == 403 and _is_saml_denial(error):
        raise InsufficientPermissionsError(
            f"{denied}: the organization uses SAML single sign-on, and the token "
            f"is not authorized for it (HTTP 403). Authorize the token: "
            f"{_SSO_GUIDE_LINK}",
            summary="Token not authorized for SAML SSO",
            description=(
                "The organization enforces SAML single sign-on and the token is "
                "not authorized for it.\nIn GitHub, configure SSO for the token "
                "and authorize the organization."
            ),
        ) from error
    if status == 403:
        raise InsufficientPermissionsError(
            f"{denied} (HTTP 403: {_detail(error)}).{_accepted_access(error)}",
            summary=denied_row.summary if denied_row else None,
            description=denied_row.description if denied_row else None,
        ) from error
    if status == 404 and not_found is not None:
        raise ConnectorValidationError(
            f"{not_found} (HTTP 404).{_accepted_access(error)}",
            summary=not_found_row.summary if not_found_row else None,
            description=not_found_row.description if not_found_row else None,
        ) from error
    if status == 422:
        # GitHub rejected the request itself (e.g. a bad state filter); index
        # attempts send the same request.
        raise ConnectorValidationError(
            f"GitHub rejected the request (HTTP 422): {_detail(error)}",
            summary="GitHub rejected the request",
            description=(
                "GitHub refused the request as sent. (HTTP 422)\nRe-run the "
                "checks. If it repeats, share the error details with support."
            ),
        ) from error
    raise UnexpectedValidationError(
        f"Unexpected GitHub response (HTTP {status}): {_detail(error)}",
        summary="Unexpected response from GitHub",
        description=(
            "GitHub answered with an error this check does not expect.\nRe-run "
            "the checks. If it repeats, share the error details with support."
        ),
    ) from error


class _GitHubCheck(CapabilityCheck[GithubConnectorConfig]):
    config_class = GithubConnectorConfig

    def __init__(
        self,
        *,
        check_id: str,
        display_name: str,
        remediation: str,
        required: bool = True,
        capability: CredentialCapability = CredentialCapability.INDEXING,
        requires_fields: frozenset[str] = _OWNER_FIELDS,
        requires_connector_config: bool = False,
        fails_when_unreachable: bool = False,
    ) -> None:
        super().__init__(
            capability=capability,
            check_id=check_id,
            display_name=display_name,
            depends_on=_DEPENDS_ON.get(check_id, ()),
            required=required,
            requires_connector_instance=False,
            requires_connector_config=requires_connector_config,
            requires_fields=requires_fields,
            remediation=remediation,
            docs_link=_DOCS_LINK,
            fails_when_unreachable=fails_when_unreachable,
        )


def _lacks_private_scope(token: GitHubTokenInfo | None) -> bool:
    return (
        token is not None
        and token.kind == GitHubTokenKind.CLASSIC
        and token.scopes is not None
        and _PRIVATE_REPOSITORY_SCOPE not in token.scopes
    )


class _AuthCheck(_GitHubCheck):
    """Signs in with ``GET /user``, which every valid token can call."""

    def __init__(self) -> None:
        super().__init__(
            check_id=_AUTH_CHECK_ID,
            display_name="Sign in to GitHub",
            remediation=(
                "Create a new personal access token (classic or fine-grained) and "
                "check the Enterprise Server URL, if one is set."
            ),
            requires_fields=frozenset(),
            fails_when_unreachable=True,
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        try:
            token: GitHubTokenInfo = _gateway(context).get_token_info()
        except ConnectorMissingCredentialError as e:
            raise CredentialInvalidError(
                "The credential has no GitHub access token.",
                summary="No token saved in the account",
                description=(
                    "The account has no API Token.\nEdit the account and paste a "
                    "token in API Token."
                ),
            ) from e
        except (requests.ConnectionError, requests.Timeout) as e:
            raise UnreachableValidationError(
                "Onyx cannot connect to GitHub. Check the Enterprise Server URL, "
                "if one is set.",
                summary="Cannot reach GitHub",
                description=(
                    "The request failed before GitHub answered, after retries.\n"
                    "Check GitHub Enterprise Server URL, if set."
                ),
            ) from e
        except GitHubApiError as e:
            _raise_for_api_error(
                e,
                denied="GitHub refused to identify the token's user",
                denied_row=_RowText(
                    summary="GitHub refused to identify the token",
                    description=(
                        "GitHub is blocking this token or its user. (HTTP 403)\n"
                        "Create a new token and paste it in the account's API "
                        "Token."
                    ),
                ),
                not_found=(
                    "Onyx found no GitHub API at the configured URL. For GitHub "
                    "Enterprise Server, enter the server URL "
                    "(https://github.example.com)"
                ),
                not_found_row=_RowText(
                    summary="No GitHub API at this URL",
                    description=(
                        "The GitHub Enterprise Server URL does not lead to a "
                        "GitHub API. (HTTP 404)\nEnter the server URL, such as "
                        "https://github.example.com."
                    ),
                ),
            )
        return CheckOutput(summary=f"Signed in as @{token.login}")


class _TokenScopesCheck(_GitHubCheck):
    """Warns when a classic token cannot read private repositories. A
    fine-grained token has no scopes; the probes check its permissions."""

    def __init__(self) -> None:
        super().__init__(
            check_id="github_token_scopes",
            display_name="Read token scopes",
            required=False,
            remediation=(
                "Add the `repo` scope to the classic token, or use a fine-grained "
                "token with read access to Contents, Issues, Pull requests and "
                "Metadata."
            ),
            requires_fields=frozenset(),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        try:
            token: GitHubTokenInfo = _gateway(context).get_token_info()
        except GitHubApiError as e:
            _raise_for_api_error(e, denied="GitHub refused to read the token")
        if token.kind != GitHubTokenKind.CLASSIC or token.scopes is None:
            raise NothingToCheckError(
                "The token is not a classic token, so it has no scopes to read. "
                "The other checks test its permissions.",
                summary="Token has no scopes to read",
                description=(
                    "Only a classic token has scopes. The other checks test this "
                    "token's permissions."
                ),
            )
        if _lacks_private_scope(token):
            raise InsufficientPermissionsError(
                "The classic token has no `repo` scope "
                f"(scopes: {', '.join(token.scopes) or 'none'}), so Onyx "
                "can index only public repositories.",
                summary="Classic token lacks the repo scope",
                description=(
                    "Private repositories would be left out of the index.\n"
                    "Edit the token in GitHub and select the repo scope."
                ),
            )
        return CheckOutput(summary="Classic token has the repo scope")


_DOCUMENT_TYPE_NAMES = ("pull requests", "issues", "documents")


class _DocumentTypesCheck(_GitHubCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id="github_document_types",
            display_name="Check selected content",
            remediation="Select pull requests, issues or files.",
            requires_fields=frozenset(),
            requires_connector_config=True,
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        config: GithubConnectorConfig = self.config(context)
        selected: list[str] = [
            name
            for name, included in zip(
                _DOCUMENT_TYPE_NAMES,
                (config.include_prs, config.include_issues, config.include_files),
                strict=True,
            )
            if included
        ]
        if not selected:
            raise ConnectorValidationError(
                "Pull requests, issues and files are all turned off, so the "
                "connector indexes nothing. Select at least one.",
                summary="Nothing selected to index",
                description=(
                    "None of pull requests, issues or documents is selected.\n"
                    "Select at least one."
                ),
            )
        return CheckOutput(summary=f"Indexing {', '.join(selected)}")


def _owner_is_organization(gateway: GitHubSourceOperations, owner: str) -> bool:
    """True for an organization, False for a user, as the connector decides:
    an owner that is not a readable organization is read as a user."""
    try:
        gateway.get_organization(login=owner)
        return True
    except GitHubRateLimitError:
        raise
    except GitHubApiError as e:
        if e.status_code == 403 and _is_saml_denial(e):
            raise
        return False


def _no_owner_row(owner: str) -> _RowText:
    return _RowText(
        summary=f"No owner named {owner}",
        description=(
            "GitHub has no organization or user with this name that the token "
            "can see. (HTTP 404)\nCheck Repository Owner."
        ),
    )


class _OwnerCheck(_GitHubCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id=_OWNER_CHECK_ID,
            display_name="Find repository owner",
            remediation=(
                "Enter the organization or user name from the repository URL "
                "(github.com/<owner>/<repository>)."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        owner: str = _owner(self.config(context))
        gateway: GitHubSourceOperations = _gateway(context)
        try:
            if _owner_is_organization(gateway, owner):
                return CheckOutput(summary=f"Found organization {owner}")
            gateway.list_user_repositories(login=owner, limit=1)
        except GitHubApiError as e:
            _raise_for_api_error(
                e,
                denied=f"GitHub refused to read the owner `{owner}`",
                denied_row=_RowText(
                    summary=f"Token cannot read owner {owner}",
                    description=(
                        "GitHub refused to show this owner to the token. (HTTP "
                        f"403)\n{_need(context, scope='repo', permission='Metadata')}"
                    ),
                ),
                not_found=f"GitHub has no organization or user named `{owner}`",
                not_found_row=_no_owner_row(owner),
            )
        return CheckOutput(summary=f"Found user {owner}")


def _list_owner_repositories(
    gateway: GitHubSourceOperations, owner: str, limit: int | None
) -> tuple[bool, list[GitHubRepository]]:
    """Whether the owner is an organization, and its repositories that the
    token sees, read as the connector reads them."""
    if _owner_is_organization(gateway, owner):
        return True, gateway.list_organization_repositories(
            org_login=owner, limit=limit
        )
    return False, gateway.list_user_repositories(login=owner, limit=limit)


def _list_repositories_denied_row(context: CapabilityCheckContext) -> _RowText:
    return _RowText(
        summary="Token cannot list the repositories",
        description=(
            "GitHub refused to list this owner's repositories. (HTTP 403)\n"
            f"{_need(context, scope='repo', permission='Metadata')}"
        ),
    )


class _RepositoriesVisibleCheck(_GitHubCheck):
    """All-repositories mode: the owner has a repository that the token
    sees. This is what ``validate_connector_settings`` probes."""

    def __init__(self) -> None:
        super().__init__(
            check_id="github_repositories_visible",
            display_name="List repositories",
            remediation=(
                f"{_TOKEN_ACCESS_HINT} A user owner lists only public repositories; "
                "enter the repository names to index private ones."
            ),
        )

    def applies(self, form_state: FormState[GithubConnectorConfig]) -> bool:
        return not parse_repository_names(form_state.config.repositories)

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        owner: str = _owner(self.config(context))
        gateway: GitHubSourceOperations = _gateway(context)
        try:
            is_organization, repositories = _list_owner_repositories(
                gateway, owner, limit=_COUNT_LIMIT
            )
        except GitHubApiError as e:
            _raise_for_api_error(
                e,
                denied=f"The token cannot list the repositories of `{owner}`",
                denied_row=_list_repositories_denied_row(context),
                not_found=f"GitHub has no organization or user named `{owner}`",
                not_found_row=_no_owner_row(owner),
            )
        if repositories:
            count: str = (
                f"{_COUNT_LIMIT}+"
                if len(repositories) >= _COUNT_LIMIT
                else str(len(repositories))
            )
            return CheckOutput(
                summary=f"{_counted(count, 'repository', 'repositories')} visible"
            )
        if is_organization:
            raise InsufficientPermissionsError(
                f"No repository of the organization `{owner}` is visible to the "
                f"token. {_TOKEN_ACCESS_HINT}",
                summary="No repositories visible to the token",
                description=(
                    "The token sees no repository of this organization.\n"
                    f"{_need(context, scope='repo', permission='Metadata')}"
                ),
            )
        raise InsufficientPermissionsError(
            f"The user `{owner}` has no public repository. GitHub lists only the "
            "public repositories of a user; enter the repository names to index "
            "private ones.",
            summary="User has no public repositories",
            description=(
                "GitHub lists only a user's public repositories, and this user "
                "has none.\nEnter the repository names to index private ones."
            ),
        )


def _repository_problem(
    error: GitHubApiError,
    *,
    owner: str,
    name: str,
    token: GitHubTokenInfo | None,
) -> str:
    """Why one listed repository cannot be read, for a combined message."""
    full_name: str = f"{owner}/{name}"
    if error.status_code == 403 and _is_saml_denial(error):
        return (
            f"`{full_name}`: the organization uses SAML single sign-on and has not "
            f"authorized the token ({_SSO_GUIDE_LINK})"
        )
    if error.status_code == 403:
        return (
            f"`{full_name}`: access denied (HTTP 403: {_detail(error)})."
            f"{_accepted_access(error)}"
        )
    if "/" in name:
        return (
            f"`{full_name}`: not found. Enter the repository name without the "
            "owner (e.g. `onyx`, not `onyx-dot-app/onyx`)"
        )
    cause: str = (
        "the classic token has no `repo` scope, which private repositories need"
        if _lacks_private_scope(token)
        else "the token's repository access does not include it"
        if token is not None and token.kind == GitHubTokenKind.FINE_GRAINED
        else "the token cannot see it"
    )
    return (
        f"`{full_name}`: not found, or private and {cause} (GitHub answers 404 "
        "for both)"
    )


def _raise_unless_denied(error: GitHubApiError, *, denied: str) -> None:
    """Raises for anything but a 403 or a 404, which the caller reports per
    repository: a bad token, a rate limit, or a GitHub outage."""
    if isinstance(error, GitHubRateLimitError) or error.status_code not in (403, 404):
        _raise_for_api_error(error, denied=denied)


def _counted(count: int | str, noun: str, plural: str) -> str:
    """``count`` with its noun: "1 repository", "3 repositories", "100+
    repositories"."""
    return f"{count} {noun if str(count) == '1' else plural}"


def _names(names: list[str]) -> str:
    return ", ".join(names)


def _not_found_line(names: list[str], token: GitHubTokenInfo | None) -> str:
    """The line after a not-found description: the names, and the likely
    cause."""
    if any("/" in name for name in names):
        return (
            f"Not found: {_names(names)}. Enter each name without the owner "
            "(onyx, not onyx-dot-app/onyx)."
        )
    if _lacks_private_scope(token):
        return f"Not found: {_names(names)}. Select the repo scope."
    return f"Not found: {_names(names)}. Check each name and the token's access."


class _ConfiguredRepositoriesCheck(_GitHubCheck):
    """Each listed repository is readable, with its root directory, as index
    attempts validate it. Indexing skips a repository it cannot read and logs
    only a warning. Some unreadable is INCOMPLETE, and the checks after it run
    on the readable ones; none readable FAILS."""

    def __init__(self) -> None:
        super().__init__(
            check_id="github_configured_repositories",
            display_name="Find selected repos",
            remediation=(
                "Check each repository name (without the owner) and the owner. "
                f"{_TOKEN_ACCESS_HINT}"
            ),
        )

    def applies(self, form_state: FormState[GithubConnectorConfig]) -> bool:
        return bool(parse_repository_names(form_state.config.repositories))

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        config: GithubConnectorConfig = self.config(context)
        owner: str = _owner(config)
        gateway: GitHubSourceOperations = _gateway(context)
        names: list[str] = parse_repository_names(config.repositories)
        problems: list[tuple[str, GitHubApiError]] = []
        content_problems: list[tuple[str, str]] = []
        for name in names:
            try:
                repository: GitHubRepository = gateway.get_repository(
                    owner=owner, name=name
                )
            except GitHubApiError as e:
                _raise_unless_denied(
                    e, denied=f"The token cannot read `{owner}/{name}`"
                )
                problems.append((name, e))
                continue
            try:
                # Index attempts read the root directory to validate the
                # repository; a fine-grained token needs Contents for it.
                gateway.list_root_contents(repo_full_name=repository.full_name)
            except GitHubApiError as e:
                _raise_unless_denied(
                    e, denied=f"The token cannot read `{repository.full_name}`"
                )
                content_problems.append(
                    (
                        repository.full_name,
                        f"`{repository.full_name}`: its files cannot be read (HTTP "
                        f"{e.status_code}: {_detail(e)}).{_accepted_access(e)} An "
                        "empty repository has no files, and index attempts reject "
                        "it",
                    )
                )
        if not problems and not content_problems:
            return CheckOutput(
                summary=f"All {len(names)} selected repositories readable"
            )
        token: GitHubTokenInfo | None = _token_info(gateway) if problems else None
        messages: list[str] = [
            _repository_problem(error, owner=owner, name=name, token=token)
            for name, error in problems
        ] + [message for _name, message in content_problems]
        message: str = (
            f"{len(messages)} of {len(names)} listed repositories cannot be "
            f"read: {'; '.join(messages)}."
        )
        missing: list[str] = [
            name for name, error in problems if error.status_code == 404
        ]
        denied: list[str] = [
            name for name, error in problems if error.status_code == 403
        ]
        unreadable: list[str] = [name for name, _message in content_problems]
        denied_line: str = (
            f"Denied: {_names(denied)}. "
            f"{_need(context, scope='repo', permission='Metadata')}"
            if denied
            else ""
        )
        if len(problems) + len(content_problems) == len(names):
            if not missing:
                raise InsufficientPermissionsError(
                    message,
                    summary=(
                        f"Token denied all {len(names)} repositories"
                        if denied
                        else f"Cannot read files of {len(names)} repositories"
                    ),
                    description=(
                        "GitHub refused the token access to these repositories.\n"
                        f"{denied_line}"
                        if denied
                        else "Index attempts read each repository's root folder "
                        "first and reject a repository they cannot read, "
                        "including an empty one."
                    ),
                )
            raise ConnectorValidationError(
                message,
                summary="No selected repo found",
                description=(
                    "None of the selected repos is visible to this account.\n"
                    f"{_not_found_line(missing, token)}"
                ),
            )
        failure_kinds: int = sum(map(bool, (missing, denied, unreadable)))
        if failure_kinds > 1:
            # One line for each kind of failure, so the row names every repository.
            row: _RowText = _RowText(
                summary=f"Cannot read {len(messages)} of {len(names)} repositories",
                description="\n".join(
                    line
                    for line in (
                        _not_found_line(missing, token) if missing else "",
                        denied_line,
                        f"Unreadable files: {_names(unreadable)}. Index attempts "
                        "reject these."
                        if unreadable
                        else "",
                    )
                    if line
                ),
            )
        elif missing:
            row = _RowText(
                summary=f"{len(missing)} of {len(names)} repositories not found",
                description=(
                    'GitHub answers "not found" for a misspelled name and for a '
                    "private repository the token cannot see.\n"
                    f"{_not_found_line(missing, token)}"
                ),
            )
        elif denied:
            row = _RowText(
                summary=f"Token denied {len(denied)} of {len(names)} repositories",
                description=(
                    "GitHub refused the token access to these repositories.\n"
                    f"{denied_line}"
                ),
            )
        else:
            row = _RowText(
                summary=(
                    f"Cannot read files of {unreadable[0]}"
                    if len(unreadable) == 1
                    else f"Cannot read files of {len(unreadable)} repositories"
                ),
                description=(
                    "Index attempts read each repository's root folder first and "
                    "reject a repository they cannot read, including an empty "
                    f"one.\nUnreadable: {_names(unreadable)}."
                ),
            )
        return CheckOutput(
            summary=row.summary, description=row.description, partial=True
        )


def _target_repositories(
    context: CapabilityCheckContext, config: GithubConnectorConfig, limit: int
) -> list[GitHubRepository]:
    """Up to ``limit`` repositories to index, read as the connector reads
    them. A repository that cannot be read is skipped: the repository checks
    report it."""
    gateway: GitHubSourceOperations = _gateway(context)
    owner: str = _owner(config)
    names: list[str] = parse_repository_names(config.repositories)
    try:
        if not names:
            return _list_owner_repositories(gateway, owner, limit=limit)[1]
        repositories: list[GitHubRepository] = []
        for name in names:
            if len(repositories) >= limit:
                break
            try:
                repository: GitHubRepository = gateway.get_repository(
                    owner=owner, name=name
                )
                # Index attempts reject a repository whose root they cannot read.
                gateway.list_root_contents(repo_full_name=repository.full_name)
            except GitHubApiError as e:
                # github_configured_repositories reports a denied, missing or
                # unreadable repository; anything else leaves this check
                # unverified.
                _raise_unless_denied(
                    e, denied=f"The token cannot read `{owner}/{name}`"
                )
                continue
            repositories.append(repository)
        return repositories
    except GitHubApiError as e:
        _raise_for_api_error(
            e,
            denied=f"The token cannot list the repositories of `{owner}`",
            denied_row=_list_repositories_denied_row(context),
            not_found=f"GitHub has no organization or user named `{owner}`",
            not_found_row=_no_owner_row(owner),
        )


def _no_repositories_error() -> NothingToCheckError:
    return NothingToCheckError(
        "No repository to index is readable, so Onyx cannot run this probe. "
        "github_repositories_visible or github_configured_repositories "
        "reports why.",
        summary="No repositories to test",
        description="No repository could be read.",
    )


def _probe_repository(
    context: CapabilityCheckContext, config: GithubConnectorConfig
) -> GitHubRepository:
    repositories: list[GitHubRepository] = _target_repositories(context, config, 1)
    if not repositories:
        raise _no_repositories_error()
    return repositories[0]


def _branch(config: GithubConnectorConfig) -> str | None:
    return (config.branch or "").strip() or None


class _BranchCheck(_GitHubCheck):
    """The configured branch exists. Indexing files stops at the first
    repository without it."""

    def __init__(self) -> None:
        super().__init__(
            check_id="github_branch",
            display_name="Find selected branch",
            remediation=(
                "Check the branch name, or leave it blank to index each "
                "repository's default branch."
            ),
        )

    def applies(self, form_state: FormState[GithubConnectorConfig]) -> bool:
        config: GithubConnectorConfig = form_state.config
        # Files read the branch. Index attempts also validate it for a single
        # listed repository, with files or without.
        return _branch(config) is not None and (
            config.include_files
            or len(parse_repository_names(config.repositories)) == 1
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        config: GithubConnectorConfig = self.config(context)
        branch: str = _branch(config) or ""
        gateway: GitHubSourceOperations = _gateway(context)
        missing: list[str] = []
        # Every listed repository; a sample in all-repositories mode.
        limit: int = (
            len(parse_repository_names(config.repositories)) or _SAMPLE_REPOSITORIES
        )
        repositories: list[GitHubRepository] = _target_repositories(
            context, config, limit
        )
        if not repositories:
            raise _no_repositories_error()
        for repository in repositories:
            try:
                gateway.get_branch(repo_full_name=repository.full_name, branch=branch)
            except GitHubApiError as e:
                if isinstance(e, GitHubRateLimitError) or e.status_code != 404:
                    _raise_for_api_error(
                        e,
                        denied=(
                            f"The token cannot read the branches of "
                            f"`{repository.full_name}`"
                        ),
                        denied_row=_RowText(
                            summary="Token cannot read branches",
                            description=(
                                "GitHub refused to show this repository's "
                                "branches. (HTTP 403)\n"
                                + _need(context, scope="repo", permission="Contents")
                            ),
                        ),
                    )
                missing.append(repository.full_name)
        if missing:
            raise ConnectorValidationError(
                f"The branch `{branch}` does not exist in "
                f"{', '.join(f'`{name}`' for name in missing)}, and indexing stops "
                "at the first repository without it. Leave the branch blank to "
                "index each repository's default branch.",
                summary=(
                    "Branch not found in "
                    f"{_counted(len(missing), 'repository', 'repositories')}"
                ),
                description=(
                    "Indexing would stop at the first repository without this "
                    f"branch: {_names(missing)}.\nCheck Branch, or leave it blank "
                    "to use each default branch."
                ),
            )
        return CheckOutput(
            summary=(
                f"Found {branch} in "
                f"{_counted(len(repositories), 'repository', 'repositories')}"
            )
        )


_LARGE_LISTING_CAVEAT = (
    "GitHub refused an offset page for this large listing. Indexing switches "
    "to cursor pages, which this check did not read."
)


class _PullRequestsCheck(_GitHubCheck):
    """Lists one page of pull requests of the first repository to index, and
    reads the first one, as indexing does."""

    def __init__(self) -> None:
        super().__init__(
            check_id="github_pull_requests",
            display_name="Sample pull requests",
            remediation=(
                "Fine-grained token: give it read access to Pull requests. Classic "
                "token: the `repo` scope for private repositories."
            ),
        )

    def applies(self, form_state: FormState[GithubConnectorConfig]) -> bool:
        return form_state.config.include_prs

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        config: GithubConnectorConfig = self.config(context)
        repository: GitHubRepository = _probe_repository(context, config)
        gateway: GitHubSourceOperations = _gateway(context)
        try:
            pull_requests: list[GitHubPullRequest] = gateway.list_pull_requests(
                repo_full_name=repository.full_name, state=config.state_filter, page=0
            )
            if pull_requests:
                gateway.get_pull_request(
                    repo_full_name=repository.full_name,
                    number=pull_requests[0].number,
                )
        except GitHubApiError as e:
            if e.status_code == 404 and not isinstance(e, GitHubRateLimitError):
                # Pull requests are turned off (e.g. a mirror); indexing skips them.
                return CheckOutput(
                    summary=f"Pull requests are off in {repository.full_name}",
                    advisories=[
                        CheckAdvisory(
                            message=(
                                "GitHub has pull requests turned off for this "
                                "repository, and indexing skips them."
                            )
                        )
                    ],
                )
            if is_cursor_pagination_required(e):
                # A large listing needs cursor pagination; indexing switches to it.
                return CheckOutput(
                    summary="Listing too large to sample",
                    advisories=[CheckAdvisory(message=_LARGE_LISTING_CAVEAT)],
                )
            _raise_for_api_error(
                e,
                denied=(
                    "The token cannot read the pull requests of "
                    f"`{repository.full_name}`"
                ),
                denied_row=_RowText(
                    summary="Token cannot read pull requests",
                    description=(
                        "GitHub refused the token access to pull requests. (HTTP "
                        "403)\n"
                        + _need(context, scope="repo", permission="Pull requests")
                    ),
                ),
            )
        if not pull_requests:
            raise InconclusiveValidationError(
                f"`{repository.full_name}` has no pull requests in the state "
                f"`{config.state_filter}`, so Onyx could not read one.",
                summary="No pull requests found to test",
                description=(
                    "The first repository has no pull requests in the selected state."
                ),
            )
        return CheckOutput(summary=f"Read pull request #{pull_requests[0].number}")


class _IssuesCheck(_GitHubCheck):
    """Lists one page of issues of the first repository to index, and reads
    the first issue that is not a pull request, as indexing does."""

    def __init__(self) -> None:
        super().__init__(
            check_id="github_issues",
            display_name="Sample issues",
            remediation=(
                "Fine-grained token: give it read access to Issues. Classic token: "
                "the `repo` scope for private repositories."
            ),
        )

    def applies(self, form_state: FormState[GithubConnectorConfig]) -> bool:
        return form_state.config.include_issues

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        config: GithubConnectorConfig = self.config(context)
        repository: GitHubRepository = _probe_repository(context, config)
        gateway: GitHubSourceOperations = _gateway(context)
        try:
            issues: list[GitHubIssue] = gateway.list_issues(
                repo_full_name=repository.full_name, state=config.state_filter, page=0
            )
            issue: GitHubIssue | None = next(
                (issue for issue in issues if not issue.is_pull_request), None
            )
            if issue is not None:
                gateway.get_issue(
                    repo_full_name=repository.full_name, number=issue.number
                )
        except GitHubApiError as e:
            if e.status_code == 404 and not isinstance(e, GitHubRateLimitError):
                # Issues are turned off for the repository; indexing skips them.
                return CheckOutput(
                    summary=f"Issues are off in {repository.full_name}",
                    advisories=[
                        CheckAdvisory(
                            message=(
                                "GitHub has issues turned off for this "
                                "repository, and indexing skips them."
                            )
                        )
                    ],
                )
            if is_cursor_pagination_required(e):
                # A large listing needs cursor pagination; indexing switches to it.
                return CheckOutput(
                    summary="Listing too large to sample",
                    advisories=[CheckAdvisory(message=_LARGE_LISTING_CAVEAT)],
                )
            _raise_for_api_error(
                e,
                denied=f"The token cannot read the issues of `{repository.full_name}`",
                denied_row=_RowText(
                    summary="Token cannot read issues",
                    description=(
                        "GitHub refused the token access to issues. (HTTP 403)\n"
                        + _need(context, scope="repo", permission="Issues")
                    ),
                ),
            )
        if issue is None:
            raise InconclusiveValidationError(
                f"The first page of `{repository.full_name}` has no issues in the "
                f"state `{config.state_filter}`, so Onyx could not read one.",
                summary="No issues found to test",
                description=(
                    "The first page of the first repository has no issues in the "
                    "selected state."
                ),
            )
        return CheckOutput(summary=f"Read issue #{issue.number}")


class _FilesCheck(_GitHubCheck):
    """Lists the file tree of the first repository to index, and reads one
    file that indexing would read."""

    def __init__(self) -> None:
        super().__init__(
            check_id="github_files",
            display_name="Sample files",
            remediation=(
                "Fine-grained token: give it read access to Contents. Classic "
                "token: the `repo` scope for private repositories."
            ),
        )

    def applies(self, form_state: FormState[GithubConnectorConfig]) -> bool:
        return form_state.config.include_files

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        config: GithubConnectorConfig = self.config(context)
        repository: GitHubRepository = _probe_repository(context, config)
        gateway: GitHubSourceOperations = _gateway(context)
        ref: str = _branch(config) or repository.default_branch or ""
        denied: str = f"The token cannot read the files of `{repository.full_name}`"
        denied_row: _RowText = _RowText(
            summary="Token cannot read files",
            description=(
                "GitHub refused the token access to file contents. (HTTP 403)\n"
                + _need(context, scope="repo", permission="Contents")
            ),
        )
        try:
            tree: GitHubGitTree = gateway.get_git_tree(
                repo_full_name=repository.full_name, ref=ref
            )
        except GitHubApiError as e:
            if e.status_code == _EMPTY_REPOSITORY_STATUS:
                # An empty repository has no tree; indexing skips it.
                raise InconclusiveValidationError(
                    f"`{repository.full_name}` is empty, so Onyx could not read a "
                    "file.",
                    summary=f"No files found in {repository.full_name}",
                    description="The first repository is empty, and indexing skips it.",
                ) from e
            if e.status_code == 404 and _branch(config) is not None:
                raise UnexpectedValidationError(
                    f"`{repository.full_name}` has no branch `{ref}`, so Onyx "
                    "cannot read its files. github_branch reports why.",
                    summary=f"No branch {ref} in {repository.full_name}",
                    description=(
                        "The selected branch is missing from the first "
                        "repository.\nCheck Branch."
                    ),
                ) from e
            _raise_for_api_error(e, denied=denied, denied_row=denied_row)
        paths: list[str] = [
            entry.path
            for entry in tree.entries
            if entry.type == "blob" and is_indexable_path(entry.path, entry.size)
        ]
        if not paths:
            raise InconclusiveValidationError(
                f"`{repository.full_name}` has no file that indexing reads.",
                summary=f"No documents found in {repository.full_name}",
                description=(
                    "The first repository has no file type that indexing reads."
                ),
            )
        try:
            gateway.get_file_content(
                repo_full_name=repository.full_name, path=paths[0], ref=ref
            )
        except GitHubApiError as e:
            _raise_for_api_error(e, denied=denied, denied_row=denied_row)
        return CheckOutput(
            summary=(
                f"{_counted(len(paths), 'document', 'documents')} found in "
                f"{repository.full_name}"
            )
        )


def build_github_indexing_checks() -> list[CapabilityCheck]:
    return [
        _AuthCheck(),
        _DocumentTypesCheck(),
        _TokenScopesCheck(),
        _OwnerCheck(),
        _RepositoriesVisibleCheck(),
        _ConfiguredRepositoriesCheck(),
        _BranchCheck(),
        _PullRequestsCheck(),
        _IssuesCheck(),
        _FilesCheck(),
    ]


# Permission sync. The EE registry registers these checks. Doc sync reads the
# visibility of each repository: public repositories are public, private ones
# map to their collaborators group, internal ones to their organization group.
# Group sync reads the collaborators of each private repository, the members of
# the organization of each internal repository, and the public email of each
# user. Both map GitHub users to Onyx users by that email.

_VISIBILITY_PUBLIC = "public"
_VISIBILITY_INTERNAL = "internal"
# Repositories a permission check reads to find private and internal ones.
_PERMISSION_SAMPLE_REPOSITORIES = 20
_SAMPLE_USERS = 5
# One login past the sample tells a complete sample from a partial one.
_USER_LISTING_LIMIT = _SAMPLE_USERS + 1
_ORG_READ_SCOPE = "read:org"
# Classic scopes that include another scope.
_IMPLYING_SCOPES: dict[str, frozenset[str]] = {
    _ORG_READ_SCOPE: frozenset({"read:org", "write:org", "admin:org"}),
}

_COLLABORATORS_HINT = (
    "GitHub lists collaborators only to an account with write (push) access to "
    "the repository. Classic token: the `repo` and `read:org` scopes. "
    "Fine-grained token: read access to Metadata."
)
_MEMBERS_HINT = (
    "Classic token: the `read:org` scope. Fine-grained token: read access to the "
    "organization's Members. Without it, GitHub lists only the public members."
)
_EMAIL_HINT = (
    "GitHub returns only the public email of a profile (Settings > Public "
    "email). Users without one get no access in Onyx."
)


def _is_private(repository: GitHubRepository) -> bool:
    """Private for group sync: a private repository, or one whose visibility
    is unknown (permission sync treats it as private)."""
    return repository.visibility not in (_VISIBILITY_PUBLIC, _VISIBILITY_INTERNAL)


class _RepositorySample(BaseModel):
    repositories: list[GitHubRepository]
    # True when permission sync reads repositories the sample left out.
    cut: bool


def _permission_repositories(
    context: CapabilityCheckContext, config: GithubConnectorConfig
) -> _RepositorySample:
    """The repositories permission sync reads, sampled. None readable is
    nothing to test: the repository checks report why."""
    # One past the sample tells whether repositories remain unread.
    repositories: list[GitHubRepository] = _target_repositories(
        context, config, _PERMISSION_SAMPLE_REPOSITORIES + 1
    )
    if not repositories:
        raise _no_repositories_error()
    return _RepositorySample(
        repositories=repositories[:_PERMISSION_SAMPLE_REPOSITORIES],
        cut=len(repositories) > _PERMISSION_SAMPLE_REPOSITORIES,
    )


class _RepositoryVisibilityCheck(_GitHubCheck):
    """The repositories list with their visibility, and an internal
    repository belongs to an organization, as doc sync needs."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id="github_repository_visibility",
            display_name="Read repo visibility",
            remediation=(
                "Give the token read access to the repositories (see the indexing "
                "checks)."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        config: GithubConnectorConfig = self.config(context)
        repositories: list[GitHubRepository] = _permission_repositories(
            context, config
        ).repositories
        orphans: list[str] = [
            repository.full_name
            for repository in repositories
            if repository.visibility == _VISIBILITY_INTERNAL
            and repository.organization is None
        ]
        if orphans:
            raise UnexpectedValidationError(
                f"GitHub returned no organization for the internal repositories "
                f"{', '.join(f'`{name}`' for name in orphans)}, so permission sync "
                "cannot give them to the organization's members.",
                summary="Internal repos have no organization",
                description=(
                    "GitHub sent internal repositories without their organization.\n"
                    "Share the error details with support."
                ),
            )
        public: int = sum(
            repository.visibility == _VISIBILITY_PUBLIC for repository in repositories
        )
        internal: int = sum(
            repository.visibility == _VISIBILITY_INTERNAL for repository in repositories
        )
        private: int = len(repositories) - public - internal
        return CheckOutput(
            summary=f"{private} private, {public} public, {internal} internal"
        )


def _scope_hint(token: GitHubTokenInfo | None, *scopes: str) -> str:
    """Names the scopes a classic token lacks, for a denial message."""
    if token is None or token.kind != GitHubTokenKind.CLASSIC or token.scopes is None:
        return ""
    granted: set[str] = set(token.scopes)
    missing: list[str] = [
        scope
        for scope in scopes
        if not granted & _IMPLYING_SCOPES.get(scope, frozenset({scope}))
    ]
    if not missing:
        return ""
    return (
        f" The classic token lacks the {', '.join(f'`{scope}`' for scope in missing)} "
        "scope."
    )


def _count(logins: list[str], limit: int) -> str:
    return f"{limit}+" if len(logins) >= limit else str(len(logins))


def _read_collaborators(
    context: CapabilityCheckContext, repository: GitHubRepository, limit: int
) -> list[str]:
    gateway: GitHubSourceOperations = _gateway(context)
    try:
        return gateway.list_repository_collaborators(
            repo_full_name=repository.full_name, limit=limit
        )
    except GitHubApiError as e:
        hint: str = _scope_hint(
            _token_info(gateway), _PRIVATE_REPOSITORY_SCOPE, _ORG_READ_SCOPE
        )
        row: _RowText = _RowText(
            summary="Token cannot list collaborators",
            description=(
                "GitHub lists collaborators only to users with write access. "
                f"(HTTP {e.status_code})\nUse a token of a user with write access "
                f"to {repository.full_name}.{hint}"
            ),
        )
        _raise_for_api_error(
            e,
            denied=(
                f"The token cannot list the collaborators of "
                f"`{repository.full_name}`.{hint} {_COLLABORATORS_HINT}"
            ),
            denied_row=row,
            not_found=(
                f"GitHub does not list the collaborators of "
                f"`{repository.full_name}` to the token.{hint} {_COLLABORATORS_HINT}"
            ),
            not_found_row=row,
        )


def _read_members(
    context: CapabilityCheckContext, org_login: str, limit: int
) -> list[str]:
    gateway: GitHubSourceOperations = _gateway(context)
    try:
        return gateway.list_organization_members(org_login=org_login, limit=limit)
    except GitHubApiError as e:
        _raise_for_api_error(
            e,
            denied=(
                f"The token cannot list the members of the organization "
                f"`{org_login}`. {_MEMBERS_HINT}"
            ),
            denied_row=_RowText(
                summary=f"Token cannot list members of {org_login}",
                description=(
                    "GitHub refused the member list. (HTTP 403)\n"
                    + _need(context, scope="read:org", permission="Members")
                ),
            ),
        )


class _CollaboratorsCheck(_GitHubCheck):
    """Lists the collaborators of the first private repository. A sync with
    only public and internal repositories reads no collaborators."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
            check_id=_COLLABORATORS_CHECK_ID,
            display_name="List collaborators",
            remediation=(
                "Use a token of an account with write access to the private "
                f"repositories. {_COLLABORATORS_HINT}"
            ),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        config: GithubConnectorConfig = self.config(context)
        sample: _RepositorySample = _permission_repositories(context, config)
        repository: GitHubRepository | None = next(
            (
                repository
                for repository in sample.repositories
                if _is_private(repository)
            ),
            None,
        )
        if repository is None and sample.cut:
            raise InconclusiveValidationError(
                f"The first {len(sample.repositories)} repositories include no "
                "private repository, so Onyx cannot verify what group sync reads "
                "for the others.",
                summary=f"No private repo in the first {len(sample.repositories)}",
                description=(
                    f"The first {len(sample.repositories)} repositories have no "
                    "private one, and the rest were not tested."
                ),
            )
        if repository is None:
            raise NothingToCheckError(
                "No repository is private, so group sync reads no collaborators.",
                summary="No private repositories to test",
                description=(
                    "Group sync reads collaborators only for private repositories, "
                    "and there are none."
                ),
            )
        logins: list[str] = _read_collaborators(context, repository, _COUNT_LIMIT)
        return CheckOutput(
            summary=(
                f"{_counted(_count(logins, _COUNT_LIMIT), 'collaborator', 'collaborators')} "
                f"in {repository.full_name}"
            )
        )


def _internal_organizations(sample: _RepositorySample) -> list[str]:
    """The organizations whose members group sync reads for the sampled
    internal repositories."""
    return sorted(
        {
            repository.organization.login
            for repository in sample.repositories
            if repository.visibility == _VISIBILITY_INTERNAL
            and repository.organization is not None
        }
    )


def _unsampled_organization(sample: _RepositorySample) -> str | None:
    """The owner organization, when the sample leaves out repositories that
    can be internal ones of it. Group sync may then read its members, but
    no internal repository proves it, so a failed read is INCOMPLETE."""
    if not sample.cut:
        return None
    return next(
        (
            repository.organization.login
            for repository in sample.repositories
            if repository.organization is not None
        ),
        None,
    )


class _OrganizationMembersCheck(_GitHubCheck):
    """Lists the members of the organization of an internal repository. A
    classic token without ``read:org`` reads only the public members, and
    GitHub reports no error for it."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
            check_id=_MEMBERS_CHECK_ID,
            display_name="List org members",
            remediation=_MEMBERS_HINT,
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        config: GithubConnectorConfig = self.config(context)
        sample: _RepositorySample = _permission_repositories(context, config)
        organizations: list[str] = _internal_organizations(sample)
        if organizations:
            return self._probe(context, organizations[0])
        unsampled: str | None = _unsampled_organization(sample)
        if unsampled is None:
            raise NothingToCheckError(
                "No repository is internal, so group sync reads no organization "
                "members.",
                summary="No internal repositories to test",
                description=(
                    "Group sync reads organization members only for internal "
                    "repositories, and there are none."
                ),
            )
        try:
            return self._probe(context, unsampled)
        except ConnectorValidationError as e:
            raise InconclusiveValidationError(
                f"The first {len(sample.repositories)} repositories include "
                f"no internal repository, so group sync may read no members "
                f"of `{unsampled}`. If it does, this fails: {e}",
                summary=f"Members of {unsampled} may be unreadable",
                description=(
                    f"No internal repository was in the first "
                    f"{len(sample.repositories)}.\n"
                    + _need(context, scope="read:org", permission="Members")
                ),
            ) from e

    def _probe(self, context: CapabilityCheckContext, org_login: str) -> CheckOutput:
        token: GitHubTokenInfo | None = _token_info(_gateway(context))
        if _scope_hint(token, _ORG_READ_SCOPE):
            raise InsufficientPermissionsError(
                f"The classic token has no `{_ORG_READ_SCOPE}` scope, so GitHub "
                f"lists only the public members of `{org_login}`, and the other "
                "members lose access to its internal repositories in Onyx.",
                summary="Classic token lacks read:org",
                description=(
                    "Private organization members would lose access to internal "
                    "repositories.\nEdit the token and select read:org."
                ),
            )
        logins: list[str] = _read_members(context, org_login, _COUNT_LIMIT)
        return CheckOutput(
            summary=(
                f"{_counted(_count(logins, _COUNT_LIMIT), 'member', 'members')} in "
                f"{org_login}"
            )
        )


class _UserEmailsCheck(_GitHubCheck):
    """Some sampled users have a public email. Group sync maps GitHub users
    to Onyx users by the public email of the profile. Fails only when no
    sampled user has one and the sample covers every user of the first
    group; a partial sample is INCOMPLETE."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
            check_id="github_user_emails",
            display_name="Read public emails",
            required=False,
            remediation=(
                "Ask the users to set a public email on their GitHub profile. "
                f"{_EMAIL_HINT}"
            ),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        config: GithubConnectorConfig = self.config(context)
        sample: _RepositorySample = _permission_repositories(context, config)
        private: GitHubRepository | None = next(
            (
                repository
                for repository in sample.repositories
                if _is_private(repository)
            ),
            None,
        )
        organizations: list[str] = _internal_organizations(sample) or [
            org for org in [_unsampled_organization(sample)] if org is not None
        ]
        if private is None and not organizations and sample.cut:
            raise InconclusiveValidationError(
                f"The first {len(sample.repositories)} repositories include no "
                "private or internal repository, so Onyx cannot verify what "
                "group sync reads for the others.",
                summary=(
                    f"No private or internal repo in first {len(sample.repositories)}"
                ),
                description=(
                    f"The first {len(sample.repositories)} repositories are all "
                    "public, and the rest were not tested."
                ),
            )
        try:
            logins: list[str] = (
                _read_collaborators(context, private, _USER_LISTING_LIMIT)
                if private is not None
                else _read_members(context, organizations[0], _USER_LISTING_LIMIT)
                if organizations
                else []
            )
        except ConnectorValidationError as e:
            raise UnexpectedValidationError(
                "Onyx cannot read the users of a group, so this check cannot run. "
                "github_repository_collaborators or github_organization_members "
                "reports why.",
                summary="Cannot read the group's users",
                description=(
                    "Onyx could not list the users to test.\nSee List "
                    "collaborators or List org members."
                ),
            ) from e
        if not logins:
            raise NothingToCheckError(
                "Group sync reads no users for these repositories.",
                summary="No users to test",
                description="Group sync reads no users for these repositories.",
            )
        gateway: GitHubSourceOperations = _gateway(context)
        sampled: list[str] = logins[:_SAMPLE_USERS]
        emails: list[str | None] = []
        for login in sampled:
            try:
                emails.append(gateway.get_user(login=login).email)
            except GitHubApiError as e:
                _raise_for_api_error(
                    e,
                    denied=f"The token cannot read the profile of `{login}`",
                    denied_row=_RowText(
                        summary="Token cannot read user profiles",
                        description=(
                            "GitHub refused to show user profiles. (HTTP 403)\n"
                            "Create a new token and paste it in the account's "
                            "API Token."
                        ),
                    ),
                )
        with_email: int = sum(1 for email in emails if email)
        if with_email:
            return CheckOutput(
                summary=f"{with_email} of {len(sampled)} users have public emails"
            )
        if len(logins) > _SAMPLE_USERS:
            raise InconclusiveValidationError(
                f"The {_SAMPLE_USERS} sampled users have no public email. Group sync "
                f"reads more users, so Onyx cannot verify the rest. {_EMAIL_HINT}",
                summary=f"First {_SAMPLE_USERS} users have no public email",
                description=(
                    "The sampled users cannot map to users here, and the rest of "
                    "the group was not read."
                ),
            )
        raise InsufficientPermissionsError(
            f"No user of the sampled group has a public email, so their access "
            f"cannot map to Onyx users. {_EMAIL_HINT}",
            summary="No sampled user has a public email",
            description=(
                "Users without a public email would get no access.\nAsk them to "
                "set a public email in their GitHub settings."
            ),
        )


def build_github_doc_permission_sync_checks() -> list[CapabilityCheck]:
    return [_RepositoryVisibilityCheck()]


def build_github_group_sync_checks() -> list[CapabilityCheck]:
    return [
        _CollaboratorsCheck(),
        _OrganizationMembersCheck(),
        _UserEmailsCheck(),
    ]
