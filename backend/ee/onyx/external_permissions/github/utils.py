from collections.abc import Callable
from enum import Enum
from typing import TypeVar

from github import Github, RateLimitExceededException
from github.GithubException import GithubException
from github.NamedUser import NamedUser
from github.PaginatedList import PaginatedList
from github.Repository import Repository
from pydantic import BaseModel, Field

from ee.onyx.db.external_perm import ExternalUserGroup
from onyx.access.models import ExternalAccess
from onyx.access.utils import build_ext_group_name_for_onyx
from onyx.configs.constants import DocumentSource
from onyx.connectors.github.rate_limit_utils import sleep_after_rate_limit_exception
from onyx.utils.logger import setup_logger

logger = setup_logger()


class GitHubVisibility(Enum):
    """GitHub repository visibility options."""

    PUBLIC = "public"
    PRIVATE = "private"
    INTERNAL = "internal"


MAX_RETRY_COUNT = 3

T = TypeVar("T")

# Higher-order function to wrap GitHub operations with retry and exception handling


def _run_with_retry(
    operation: Callable[[], T],
    description: str,
    github_client: Github,
    retry_count: int = 0,
) -> T | None:
    """Execute a GitHub operation with retry on rate limit and exception handling."""
    logger.debug("Starting operation '%s', attempt %s", description, retry_count + 1)
    try:
        result = operation()
        logger.debug("Operation '%s' completed successfully", description)
        return result
    except RateLimitExceededException:
        if retry_count < MAX_RETRY_COUNT:
            sleep_after_rate_limit_exception(github_client)
            logger.warning(
                "Rate limit exceeded while %s. Retrying... (attempt %s/%s)",
                description,
                retry_count + 1,
                MAX_RETRY_COUNT,
            )
            return _run_with_retry(
                operation, description, github_client, retry_count + 1
            )
        else:
            error_msg = f"Max retries exceeded for {description}"
            logger.exception(error_msg)
            raise RuntimeError(error_msg)
    except GithubException as e:
        logger.warning("GitHub API error during %s: %s", description, e)
        return None
    except Exception as e:
        logger.exception("Unexpected error during %s: %s", description, e)
        return None


class UserInfo(BaseModel):
    login: str
    email: str | None = None


class GitHubGroupSyncCache(BaseModel):
    users_by_login: dict[str, UserInfo] = Field(default_factory=dict)
    organization_groups_by_id: dict[int, ExternalUserGroup] = Field(
        default_factory=dict
    )


def _get_user_info(user: NamedUser, cache: GitHubGroupSyncCache) -> UserInfo:
    login = user.login
    cached_user = cache.users_by_login.get(login)
    if cached_user is not None:
        return cached_user

    user_info = UserInfo(login=login, email=user.email)
    if user_info.email is None:
        logger.warning("GitHub user %s has no email", login)
    cache.users_by_login[login] = user_info
    return user_info


def _fetch_organization_group(
    github_client: Github, repo: Repository, cache: GitHubGroupSyncCache
) -> ExternalUserGroup:
    organization = repo.organization
    if organization is None:
        raise ValueError(f"Repository {repo.full_name} has no organization")

    cached_group = cache.organization_groups_by_id.get(organization.id)
    if cached_group is not None:
        return cached_group

    org_name = organization.login
    logger.info("Fetching organization members for %s", org_name)

    org = _run_with_retry(
        lambda: github_client.get_organization(org_name),
        f"get organization {org_name}",
        github_client,
    )
    if not org:
        logger.error("Failed to fetch organization %s", org_name)
        raise RuntimeError(f"Failed to fetch organization {org_name}")

    members: PaginatedList[NamedUser] | list[NamedUser] = (
        _run_with_retry(
            lambda: org.get_members(filter_="all"),
            f"get members for organization {org_name}",
            github_client,
        )
        or []
    )

    user_emails = {
        user_info.email
        for member in members
        if (user_info := _get_user_info(member, cache)).email
    }
    organization_group = ExternalUserGroup(
        id=form_organization_group_id(organization.id),
        user_emails=list(user_emails),
    )
    cache.organization_groups_by_id[organization.id] = organization_group

    logger.info("Fetched %s members for organization %s", len(user_emails), org_name)
    return organization_group


def _fetch_repository_collaborator_emails(
    repo: Repository, github_client: Github, cache: GitHubGroupSyncCache
) -> set[str]:
    """Fetch every user with repository access, regardless of the grant source."""
    collaborators: PaginatedList[NamedUser] | list[NamedUser] = (
        _run_with_retry(
            repo.get_collaborators,
            f"get collaborators for repository {repo.full_name}",
            github_client,
        )
        or []
    )
    user_emails = {
        user_info.email
        for collaborator in collaborators
        if (user_info := _get_user_info(collaborator, cache)).email
    }
    logger.info(
        "Fetched %s collaborators with emails for repository %s",
        len(user_emails),
        repo.full_name,
    )
    return user_emails


def form_collaborators_group_id(repository_id: int) -> str:
    """Generate group ID for repository collaborators."""
    if not repository_id:
        logger.exception("Repository ID is required to generate collaborators group ID")
        raise ValueError("Repository ID must be set to generate group ID.")
    group_id = f"{repository_id}_collaborators"
    return group_id


def form_organization_group_id(organization_id: int) -> str:
    """Generate group ID for organization using organization ID."""
    if not organization_id:
        logger.exception(
            "Organization ID is required to generate organization group ID"
        )
        raise ValueError("Organization ID must be set to generate group ID.")
    group_id = f"{organization_id}_organization"
    return group_id


def get_repository_visibility(repo: Repository) -> GitHubVisibility:
    """
    Get the visibility of a repository.
    Returns GitHubVisibility enum member.
    """
    if hasattr(repo, "visibility"):
        visibility = repo.visibility
        logger.info(
            "Repository %s visibility from attribute: %s", repo.full_name, visibility
        )
        try:
            return GitHubVisibility(visibility)
        except ValueError:
            logger.warning(
                "Unknown visibility '%s' for repo %s, defaulting to private",
                visibility,
                repo.full_name,
            )
            return GitHubVisibility.PRIVATE

    logger.info("Repository %s is private", repo.full_name)
    return GitHubVisibility.PRIVATE


def get_external_access_permission(
    repo: Repository,
    github_client: Github,  # noqa: ARG001
    add_prefix: bool = False,
) -> ExternalAccess:
    """
    Get the external access permission for a repository.
    Uses group-based permissions for efficiency and scalability.

    add_prefix: When this method is called during the initial permission sync via the connector,
                the group ID isn't prefixed with the source while inserting the document record.
                So in that case, set add_prefix to True, allowing the method itself to handle
                prefixing. However, when the same method is invoked from doc_sync, our system
                already adds the prefix to the group ID while processing the ExternalAccess object.
    """
    repo_visibility = get_repository_visibility(repo)
    logger.info(
        "Generating ExternalAccess for %s: visibility=%s",
        repo.full_name,
        repo_visibility.value,
    )

    if repo_visibility == GitHubVisibility.PUBLIC:
        logger.info(
            "Repository %s is public - allowing access to all users", repo.full_name
        )
        return ExternalAccess(
            external_user_emails=set(),
            external_user_group_ids=set(),
            is_public=True,
        )
    elif repo_visibility == GitHubVisibility.PRIVATE:
        logger.info(
            "Repository %s is private - setting up restricted access", repo.full_name
        )

        collaborators_group_id = form_collaborators_group_id(repo.id)
        if add_prefix:
            collaborators_group_id = build_ext_group_name_for_onyx(
                source=DocumentSource.GITHUB,
                ext_group_name=collaborators_group_id,
            )
        group_ids = {collaborators_group_id}

        logger.info("ExternalAccess groups for %s: %s", repo.full_name, group_ids)
        return ExternalAccess(
            external_user_emails=set(),
            external_user_group_ids=group_ids,
            is_public=False,
        )
    else:
        logger.info(
            "Repository %s is internal - using its organization group", repo.full_name
        )
        organization = repo.organization
        if organization is None:
            raise ValueError(f"Repository {repo.full_name} has no organization")
        org_group_id = form_organization_group_id(organization.id)
        if add_prefix:
            org_group_id = build_ext_group_name_for_onyx(
                source=DocumentSource.GITHUB,
                ext_group_name=org_group_id,
            )
        group_ids = {org_group_id}
        logger.info("ExternalAccess groups for %s: %s", repo.full_name, group_ids)
        return ExternalAccess(
            external_user_emails=set(),
            external_user_group_ids=group_ids,
            is_public=False,
        )


def get_external_user_group(
    repo: Repository,
    github_client: Github,
    cache: GitHubGroupSyncCache,
) -> list[ExternalUserGroup]:
    """Build the repository group while sharing users and organizations across repos."""
    repo_visibility = get_repository_visibility(repo)
    logger.info(
        "Generating ExternalUserGroups for %s: visibility=%s",
        repo.full_name,
        repo_visibility.value,
    )

    if repo_visibility == GitHubVisibility.PRIVATE:
        logger.info("Processing private repository %s", repo.full_name)
        user_emails = _fetch_repository_collaborator_emails(repo, github_client, cache)
        if not user_emails:
            return []

        collaborators_group = ExternalUserGroup(
            id=form_collaborators_group_id(repo.id),
            user_emails=list(user_emails),
        )
        logger.info(
            "Created collaborators group with %s emails for private repository %s",
            len(user_emails),
            repo.full_name,
        )
        return [collaborators_group]

    if repo_visibility == GitHubVisibility.INTERNAL:
        logger.info("Processing internal repository %s", repo.full_name)
        organization = repo.organization
        if organization is None:
            raise ValueError(f"Repository {repo.full_name} has no organization")
        organization_id = organization.id
        if organization_id in cache.organization_groups_by_id:
            return []
        return [_fetch_organization_group(github_client, repo, cache)]

    logger.info("Repository %s is public - no user groups needed", repo.full_name)
    return []
