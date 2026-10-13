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

from pydantic import BaseModel

from onyx.connectors.capability_checks.form_state import FormState
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CredentialCapability,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
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

_TOKEN_ACCESS_HINT = (
    "Classic token: the `repo` scope reads private repositories. Fine-grained "
    "token: its resource owner must be the repository owner, and its repository "
    "access must include the repositories."
)


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


def _raise_for_api_error(
    error: GitHubApiError,
    *,
    denied: str,
    not_found: str | None = None,
) -> NoReturn:
    """Maps a GitHub API error onto the validation-exception family.
    ``denied`` explains a 403 for this probe, ``not_found`` a 404."""
    if isinstance(error, GitHubRateLimitError):
        kind: str = "secondary rate limit" if error.secondary else "rate limit"
        raise UnexpectedValidationError(
            f"GitHub's {kind} stopped the check. Run the checks again later."
        ) from error
    status: int | None = error.status_code
    if status == 401:
        raise CredentialExpiredError(
            "GitHub rejected the token (HTTP 401). The token is wrong, expired, "
            "or revoked. Create a new token."
        ) from error
    if status == 403 and _is_saml_denial(error):
        raise InsufficientPermissionsError(
            f"{denied}: the organization uses SAML single sign-on, and the token "
            f"is not authorized for it (HTTP 403). Authorize the token: "
            f"{_SSO_GUIDE_LINK}"
        ) from error
    if status == 403:
        raise InsufficientPermissionsError(
            f"{denied} (HTTP 403: {_detail(error)}).{_accepted_access(error)}"
        ) from error
    if status == 404 and not_found is not None:
        raise ConnectorValidationError(
            f"{not_found} (HTTP 404).{_accepted_access(error)}"
        ) from error
    if status == 422:
        # GitHub rejected the request itself (e.g. a bad state filter); index
        # attempts send the same request.
        raise ConnectorValidationError(
            f"GitHub rejected the request (HTTP 422): {_detail(error)}"
        ) from error
    raise UnexpectedValidationError(
        f"Unexpected GitHub response (HTTP {status}): {_detail(error)}"
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
    ) -> None:
        super().__init__(
            capability=capability,
            check_id=check_id,
            display_name=display_name,
            required=required,
            requires_connector_instance=False,
            requires_connector_config=requires_connector_config,
            requires_fields=requires_fields,
            remediation=remediation,
            docs_link=_DOCS_LINK,
        )


def _token_info(gateway: GitHubSourceOperations) -> GitHubTokenInfo | None:
    """The token's kind and scopes, or None when GitHub does not answer.
    github_auth reports why."""
    try:
        return gateway.get_token_info()
    except GitHubApiError:
        return None


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
            check_id="github_auth",
            display_name="Token signs in",
            remediation=(
                "Create a new personal access token (classic or fine-grained) and "
                "check the Enterprise Server URL, if one is set."
            ),
            requires_fields=frozenset(),
        )

    def run(self, context: CapabilityCheckContext) -> None:
        try:
            _gateway(context).get_token_info()
        except GitHubApiError as e:
            _raise_for_api_error(
                e,
                denied="GitHub refused to identify the token's user",
                not_found=(
                    "Onyx found no GitHub API at the configured URL. For GitHub "
                    "Enterprise Server, enter the server URL "
                    "(https://github.example.com)"
                ),
            )


class _TokenScopesCheck(_GitHubCheck):
    """Warns when a classic token cannot read private repositories. A
    fine-grained token has no scopes; the probes check its permissions."""

    def __init__(self) -> None:
        super().__init__(
            check_id="github_token_scopes",
            display_name="Classic token can read private repositories",
            required=False,
            remediation=(
                "Add the `repo` scope to the classic token, or use a fine-grained "
                "token with read access to Contents, Issues, Pull requests and "
                "Metadata."
            ),
            requires_fields=frozenset(),
        )

    def run(self, context: CapabilityCheckContext) -> None:
        try:
            token: GitHubTokenInfo = _gateway(context).get_token_info()
        except GitHubApiError as e:
            raise UnexpectedValidationError(
                "Onyx cannot read the token's scopes. github_auth reports why."
            ) from e
        if _lacks_private_scope(token):
            raise InsufficientPermissionsError(
                "The classic token has no `repo` scope "
                f"(scopes: {', '.join(token.scopes or []) or 'none'}), so Onyx "
                "can index only public repositories."
            )


class _DocumentTypesCheck(_GitHubCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id="github_document_types",
            display_name="Something is selected to index",
            remediation="Select pull requests, issues or files.",
            requires_fields=frozenset(),
            requires_connector_config=True,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        config: GithubConnectorConfig = self.config(context)
        if not (config.include_prs or config.include_issues or config.include_files):
            raise ConnectorValidationError(
                "Pull requests, issues and files are all turned off, so the "
                "connector indexes nothing. Select at least one."
            )


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


class _OwnerCheck(_GitHubCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id="github_owner",
            display_name="Repository owner exists",
            remediation=(
                "Enter the organization or user name from the repository URL "
                "(github.com/<owner>/<repository>)."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> None:
        owner: str = _owner(self.config(context))
        gateway: GitHubSourceOperations = _gateway(context)
        try:
            if _owner_is_organization(gateway, owner):
                return
            gateway.list_user_repositories(login=owner, limit=1)
        except GitHubApiError as e:
            _raise_for_api_error(
                e,
                denied=f"GitHub refused to read the owner `{owner}`",
                not_found=f"GitHub has no organization or user named `{owner}`",
            )


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


class _RepositoriesVisibleCheck(_GitHubCheck):
    """All-repositories mode: the owner has a repository that the token
    sees. This is what ``validate_connector_settings`` probes."""

    def __init__(self) -> None:
        super().__init__(
            check_id="github_repositories_visible",
            display_name="Repositories are visible",
            remediation=(
                f"{_TOKEN_ACCESS_HINT} A user owner lists only public repositories; "
                "enter the repository names to index private ones."
            ),
        )

    def applies(self, form_state: FormState[GithubConnectorConfig]) -> bool:
        return not parse_repository_names(form_state.config.repositories)

    def run(self, context: CapabilityCheckContext) -> None:
        owner: str = _owner(self.config(context))
        gateway: GitHubSourceOperations = _gateway(context)
        try:
            is_organization, repositories = _list_owner_repositories(
                gateway, owner, limit=1
            )
        except GitHubApiError as e:
            _raise_for_api_error(
                e,
                denied=f"The token cannot list the repositories of `{owner}`",
                not_found=f"GitHub has no organization or user named `{owner}`",
            )
        if repositories:
            return
        if is_organization:
            raise InsufficientPermissionsError(
                f"No repository of the organization `{owner}` is visible to the "
                f"token. {_TOKEN_ACCESS_HINT}"
            )
        raise InsufficientPermissionsError(
            f"The user `{owner}` has no public repository. GitHub lists only the "
            "public repositories of a user; enter the repository names to index "
            "private ones."
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


class _ConfiguredRepositoriesCheck(_GitHubCheck):
    """Each listed repository is readable, with its root directory, as index
    attempts validate it. Indexing skips a repository it cannot read and logs
    only a warning."""

    def __init__(self) -> None:
        super().__init__(
            check_id="github_configured_repositories",
            display_name="Listed repositories are readable",
            remediation=(
                "Check each repository name (without the owner) and the owner. "
                f"{_TOKEN_ACCESS_HINT}"
            ),
        )

    def applies(self, form_state: FormState[GithubConnectorConfig]) -> bool:
        return bool(parse_repository_names(form_state.config.repositories))

    def run(self, context: CapabilityCheckContext) -> None:
        config: GithubConnectorConfig = self.config(context)
        owner: str = _owner(config)
        gateway: GitHubSourceOperations = _gateway(context)
        names: list[str] = parse_repository_names(config.repositories)
        problems: list[tuple[str, GitHubApiError]] = []
        content_problems: list[str] = []
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
                    f"`{repository.full_name}`: its files cannot be read (HTTP "
                    f"{e.status_code}: {_detail(e)}).{_accepted_access(e)} An "
                    "empty repository has no files, and index attempts reject it"
                )
        if not problems and not content_problems:
            return
        token: GitHubTokenInfo | None = _token_info(gateway) if problems else None
        messages: list[str] = [
            _repository_problem(error, owner=owner, name=name, token=token)
            for name, error in problems
        ] + content_problems
        message: str = (
            f"{len(messages)} of {len(names)} listed repositories cannot be "
            f"read: {'; '.join(messages)}."
        )
        if not content_problems and all(
            error.status_code == 404 for _name, error in problems
        ):
            raise ConnectorValidationError(message)
        raise InsufficientPermissionsError(message)


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
                repositories.append(gateway.get_repository(owner=owner, name=name))
            except GitHubApiError as e:
                # github_configured_repositories reports a denied or missing
                # repository; anything else leaves this check unverified.
                _raise_unless_denied(
                    e, denied=f"The token cannot read `{owner}/{name}`"
                )
        return repositories
    except GitHubRateLimitError as e:
        _raise_for_api_error(e, denied=f"The token cannot read `{owner}`")
    except GitHubApiError as e:
        raise UnexpectedValidationError(
            f"Onyx cannot read the repositories of `{owner}`, so this check "
            "cannot run. github_owner reports why."
        ) from e


def _probe_repository(
    context: CapabilityCheckContext, config: GithubConnectorConfig
) -> GitHubRepository:
    repositories: list[GitHubRepository] = _target_repositories(context, config, 1)
    if not repositories:
        raise UnexpectedValidationError(
            "No repository to index is readable, so Onyx cannot run this probe. "
            "github_repositories_visible or github_configured_repositories "
            "reports why."
        )
    return repositories[0]


def _branch(config: GithubConnectorConfig) -> str | None:
    return (config.branch or "").strip() or None


class _BranchCheck(_GitHubCheck):
    """The configured branch exists. Indexing files stops at the first
    repository without it."""

    def __init__(self) -> None:
        super().__init__(
            check_id="github_branch",
            display_name="Branch exists",
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

    def run(self, context: CapabilityCheckContext) -> None:
        config: GithubConnectorConfig = self.config(context)
        branch: str = _branch(config) or ""
        gateway: GitHubSourceOperations = _gateway(context)
        missing: list[str] = []
        # Every listed repository; a sample in all-repositories mode.
        limit: int = (
            len(parse_repository_names(config.repositories)) or _SAMPLE_REPOSITORIES
        )
        for repository in _target_repositories(context, config, limit):
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
                    )
                missing.append(repository.full_name)
        if missing:
            raise ConnectorValidationError(
                f"The branch `{branch}` does not exist in "
                f"{', '.join(f'`{name}`' for name in missing)}, and indexing stops "
                "at the first repository without it. Leave the branch blank to "
                "index each repository's default branch."
            )


class _PullRequestsCheck(_GitHubCheck):
    """Lists one page of pull requests of the first repository to index, and
    reads the first one, as indexing does."""

    def __init__(self) -> None:
        super().__init__(
            check_id="github_pull_requests",
            display_name="Pull requests are readable",
            remediation=(
                "Fine-grained token: give it read access to Pull requests. Classic "
                "token: the `repo` scope for private repositories."
            ),
        )

    def applies(self, form_state: FormState[GithubConnectorConfig]) -> bool:
        return form_state.config.include_prs

    def run(self, context: CapabilityCheckContext) -> None:
        config: GithubConnectorConfig = self.config(context)
        repository: GitHubRepository = _probe_repository(context, config)
        gateway: GitHubSourceOperations = _gateway(context)
        denied: str = (
            f"The token cannot read the pull requests of `{repository.full_name}`"
        )
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
                return
            if is_cursor_pagination_required(e):
                # A large listing needs cursor pagination; indexing switches to it.
                return
            _raise_for_api_error(e, denied=denied)


class _IssuesCheck(_GitHubCheck):
    """Lists one page of issues of the first repository to index, and reads
    the first issue that is not a pull request, as indexing does."""

    def __init__(self) -> None:
        super().__init__(
            check_id="github_issues",
            display_name="Issues are readable",
            remediation=(
                "Fine-grained token: give it read access to Issues. Classic token: "
                "the `repo` scope for private repositories."
            ),
        )

    def applies(self, form_state: FormState[GithubConnectorConfig]) -> bool:
        return form_state.config.include_issues

    def run(self, context: CapabilityCheckContext) -> None:
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
                return
            if is_cursor_pagination_required(e):
                # A large listing needs cursor pagination; indexing switches to it.
                return
            _raise_for_api_error(
                e,
                denied=f"The token cannot read the issues of `{repository.full_name}`",
            )


class _FilesCheck(_GitHubCheck):
    """Lists the file tree of the first repository to index, and reads one
    file that indexing would read."""

    def __init__(self) -> None:
        super().__init__(
            check_id="github_files",
            display_name="Files are readable",
            remediation=(
                "Fine-grained token: give it read access to Contents. Classic "
                "token: the `repo` scope for private repositories."
            ),
        )

    def applies(self, form_state: FormState[GithubConnectorConfig]) -> bool:
        return form_state.config.include_files

    def run(self, context: CapabilityCheckContext) -> None:
        config: GithubConnectorConfig = self.config(context)
        repository: GitHubRepository = _probe_repository(context, config)
        gateway: GitHubSourceOperations = _gateway(context)
        ref: str = _branch(config) or repository.default_branch or ""
        denied: str = f"The token cannot read the files of `{repository.full_name}`"
        try:
            tree: GitHubGitTree = gateway.get_git_tree(
                repo_full_name=repository.full_name, ref=ref
            )
        except GitHubApiError as e:
            if e.status_code == _EMPTY_REPOSITORY_STATUS:
                # An empty repository has no tree; indexing skips it.
                return
            if e.status_code == 404 and _branch(config) is not None:
                raise UnexpectedValidationError(
                    f"`{repository.full_name}` has no branch `{ref}`, so Onyx "
                    "cannot read its files. github_branch reports why."
                ) from e
            _raise_for_api_error(e, denied=denied)
        path: str | None = next(
            (
                entry.path
                for entry in tree.entries
                if entry.type == "blob" and is_indexable_path(entry.path, entry.size)
            ),
            None,
        )
        if path is None:
            return
        try:
            gateway.get_file_content(
                repo_full_name=repository.full_name, path=path, ref=ref
            )
        except GitHubApiError as e:
            _raise_for_api_error(e, denied=denied)


def build_github_indexing_checks() -> list[CapabilityCheck]:
    return [
        _AuthCheck(),
        _TokenScopesCheck(),
        _DocumentTypesCheck(),
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
    INDETERMINATE: the repository checks report why."""
    # One past the sample tells whether repositories remain unread.
    repositories: list[GitHubRepository] = _target_repositories(
        context, config, _PERMISSION_SAMPLE_REPOSITORIES + 1
    )
    if not repositories:
        raise UnexpectedValidationError(
            "No repository to sync is readable, so Onyx cannot run this probe. "
            "github_repositories_visible or github_configured_repositories "
            "reports why."
        )
    return _RepositorySample(
        repositories=repositories[:_PERMISSION_SAMPLE_REPOSITORIES],
        cut=len(repositories) > _PERMISSION_SAMPLE_REPOSITORIES,
    )


def _raise_if_sample_was_cut(sample: _RepositorySample, kind: str) -> None:
    """No sampled repository is of the kind a probe needs. When the sample
    leaves repositories out, the sync can still read one: INDETERMINATE."""
    if sample.cut:
        raise UnexpectedValidationError(
            f"The first {len(sample.repositories)} repositories include no {kind} "
            "repository, so Onyx cannot verify what group sync reads for the "
            "others."
        )


class _RepositoryVisibilityCheck(_GitHubCheck):
    """The repositories list with their visibility, and an internal
    repository belongs to an organization, as doc sync needs."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id="github_repository_visibility",
            display_name="Repository visibility is readable",
            remediation=(
                "Give the token read access to the repositories (see the indexing "
                "checks)."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> None:
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
            raise ConnectorValidationError(
                f"GitHub returned no organization for the internal repositories "
                f"{', '.join(f'`{name}`' for name in orphans)}, so permission sync "
                "cannot give them to the organization's members."
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


def _read_collaborators(
    context: CapabilityCheckContext, repository: GitHubRepository
) -> list[str]:
    gateway: GitHubSourceOperations = _gateway(context)
    try:
        return gateway.list_repository_collaborators(
            repo_full_name=repository.full_name, limit=_USER_LISTING_LIMIT
        )
    except GitHubApiError as e:
        hint: str = _scope_hint(
            _token_info(gateway), _PRIVATE_REPOSITORY_SCOPE, _ORG_READ_SCOPE
        )
        _raise_for_api_error(
            e,
            denied=(
                f"The token cannot list the collaborators of "
                f"`{repository.full_name}`.{hint} {_COLLABORATORS_HINT}"
            ),
            not_found=(
                f"GitHub does not list the collaborators of "
                f"`{repository.full_name}` to the token.{hint} {_COLLABORATORS_HINT}"
            ),
        )


def _read_members(context: CapabilityCheckContext, org_login: str) -> list[str]:
    gateway: GitHubSourceOperations = _gateway(context)
    try:
        return gateway.list_organization_members(
            org_login=org_login, limit=_USER_LISTING_LIMIT
        )
    except GitHubApiError as e:
        _raise_for_api_error(
            e,
            denied=(
                f"The token cannot list the members of the organization "
                f"`{org_login}`. {_MEMBERS_HINT}"
            ),
        )


class _CollaboratorsCheck(_GitHubCheck):
    """Lists the collaborators of the first private repository. A sync with
    only public and internal repositories reads no collaborators."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
            check_id="github_repository_collaborators",
            display_name="Repository collaborators are readable",
            remediation=(
                "Use a token of an account with write access to the private "
                f"repositories. {_COLLABORATORS_HINT}"
            ),
        )

    def run(self, context: CapabilityCheckContext) -> None:
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
        if repository is None:
            _raise_if_sample_was_cut(sample, "private")
            return
        _read_collaborators(context, repository)


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
    no internal repository proves it, so a failed read is INDETERMINATE."""
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
            check_id="github_organization_members",
            display_name="Organization members are readable",
            remediation=_MEMBERS_HINT,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        config: GithubConnectorConfig = self.config(context)
        sample: _RepositorySample = _permission_repositories(context, config)
        organizations: list[str] = _internal_organizations(sample)
        if not organizations:
            unsampled: str | None = _unsampled_organization(sample)
            if unsampled is None:
                # No internal repository: group sync reads no members.
                return
            try:
                self._probe(context, unsampled)
            except ConnectorValidationError as e:
                raise UnexpectedValidationError(
                    f"The first {len(sample.repositories)} repositories include "
                    f"no internal repository, so group sync may read no members "
                    f"of `{unsampled}`. If it does, this fails: {e}"
                ) from e
            return
        self._probe(context, organizations[0])

    def _probe(self, context: CapabilityCheckContext, org_login: str) -> None:
        token: GitHubTokenInfo | None = _token_info(_gateway(context))
        if _scope_hint(token, _ORG_READ_SCOPE):
            raise InsufficientPermissionsError(
                f"The classic token has no `{_ORG_READ_SCOPE}` scope, so GitHub "
                f"lists only the public members of `{org_login}`, and the other "
                "members lose access to its internal repositories in Onyx."
            )
        _read_members(context, org_login)


class _UserEmailsCheck(_GitHubCheck):
    """Some sampled users have a public email. Group sync maps GitHub users
    to Onyx users by the public email of the profile. Fails only when no
    sampled user has one and the sample covers every user of the first
    group; a partial sample is INDETERMINATE."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
            check_id="github_user_emails",
            display_name="Users have public emails",
            required=False,
            remediation=(
                "Ask the users to set a public email on their GitHub profile. "
                f"{_EMAIL_HINT}"
            ),
        )

    def run(self, context: CapabilityCheckContext) -> None:
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
        if private is None and not organizations:
            _raise_if_sample_was_cut(sample, "private or internal")
            return
        try:
            logins: list[str] = (
                _read_collaborators(context, private)
                if private is not None
                else _read_members(context, organizations[0])
                if organizations
                else []
            )
        except ConnectorValidationError as e:
            raise UnexpectedValidationError(
                "Onyx cannot read the users of a group, so this check cannot run. "
                "github_repository_collaborators or github_organization_members "
                "reports why."
            ) from e
        if not logins:
            return
        gateway: GitHubSourceOperations = _gateway(context)
        emails: list[str | None] = []
        for login in logins[:_SAMPLE_USERS]:
            try:
                emails.append(gateway.get_user(login=login).email)
            except GitHubApiError as e:
                _raise_for_api_error(
                    e, denied=f"The token cannot read the profile of `{login}`"
                )
        if any(emails):
            return
        if len(logins) > _SAMPLE_USERS:
            raise UnexpectedValidationError(
                f"The {_SAMPLE_USERS} sampled users have no public email. Group sync "
                f"reads more users, so Onyx cannot verify the rest. {_EMAIL_HINT}"
            )
        raise InsufficientPermissionsError(
            f"No user of the sampled group has a public email, so their access "
            f"cannot map to Onyx users. {_EMAIL_HINT}"
        )


def build_github_doc_permission_sync_checks() -> list[CapabilityCheck]:
    return [_RepositoryVisibilityCheck()]


def build_github_group_sync_checks() -> list[CapabilityCheck]:
    return [
        _CollaboratorsCheck(),
        _OrganizationMembersCheck(),
        _UserEmailsCheck(),
    ]
