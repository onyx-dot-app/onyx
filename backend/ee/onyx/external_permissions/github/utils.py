from dataclasses import dataclass
from typing import List
from typing import Optional

from github import Github
from github import RateLimitExceededException
from github.GithubException import GithubException
from github.Repository import Repository

from onyx.connectors.github.rate_limit_utils import sleep_after_rate_limit_exception
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Maximum number of retries for rate limit handling
MAX_RETRY_COUNT = 3


@dataclass
class UserInfo:
    """Represents a GitHub user with their basic information."""

    login: str
    name: Optional[str] = None
    email: Optional[str] = None


@dataclass
class TeamInfo:
    """Represents a GitHub team with its members."""

    name: str
    slug: str
    members: List[UserInfo]


@dataclass
class RepositoryPermissionsBase:
    """Base class for repository permissions with common fields and methods."""

    repository_name: str
    repository_id: int
    repository_owner: str
    repository_owner_type: str  # "Organization" or "User"
    is_public: bool = False
    organization_name: Optional[str] = None

    @property
    def collaborators_group_id(self) -> str:
        """Generate group ID for repository collaborators."""
        if not self.repository_owner or not self.repository_id:
            raise ValueError(
                "Repository owner and ID must be set to generate group ID."
            )
        return f"{self.repository_owner}_{self.repository_id}_collaborators"

    @property
    def owners_group_id(self) -> str:
        """Generate group ID for repository owners."""
        if not self.repository_owner or not self.repository_id:
            raise ValueError(
                "Repository owner and ID must be set to generate group ID."
            )
        return f"{self.repository_owner}_{self.repository_id}_owners"

    @property
    def outside_collaborators_group_id(self) -> str:
        """Generate group ID for repository outside collaborators."""
        if not self.repository_owner or not self.repository_id:
            raise ValueError(
                "Repository owner and ID must be set to generate group ID."
            )
        return f"{self.repository_owner}_{self.repository_id}_outside_collaborators"


@dataclass
class RepositoryPermissions(RepositoryPermissionsBase):
    """Comprehensive repository permissions data structure."""

    org_members: List[UserInfo] = None
    teams: List[TeamInfo] = None
    collaborators: List[UserInfo] = None
    outside_collaborators: List[UserInfo] = None

    def __post_init__(self):
        """Initialize empty lists if None."""
        if self.org_members is None:
            self.org_members = []
        if self.teams is None:
            self.teams = []
        if self.collaborators is None:
            self.collaborators = []
        if self.outside_collaborators is None:
            self.outside_collaborators = []


@dataclass
class RepositoryPermissionsSummary(RepositoryPermissionsBase):
    """Lightweight repository permissions summary with boolean flags for member presence."""

    has_org_members: bool = False
    has_teams: bool = False
    has_collaborators: bool = False
    has_outside_collaborators: bool = False
    team_count: int = 0
    teams: List[TeamInfo] = None

    def __post_init__(self):
        """Initialize empty lists if None."""
        if self.teams is None:
            self.teams = []


def _fetch_organization_members(
    github_client: Github, org_name: str, retry_count: int = 0
) -> List[UserInfo]:
    """Fetch all organization members including owners and regular members."""
    org_members = []
    try:
        logger.info(f"Fetching organization members for {org_name}")
        org = github_client.get_organization(org_name)

        # Get all members (both public and private)
        all_members = org.get_members(filter_="all")
        for member in all_members:
            member_info = UserInfo(
                login=member.login, name=member.name, email=member.email
            )
            org_members.append(member_info)
    except RateLimitExceededException:
        if retry_count < MAX_RETRY_COUNT:
            sleep_after_rate_limit_exception(github_client)
            logger.warning(
                f"Rate limit exceeded while fetching organization members for "
                f"{org_name}. Retrying... (attempt {retry_count + 1}/{MAX_RETRY_COUNT})"
            )
            return _fetch_organization_members(github_client, org_name, retry_count + 1)
        else:
            error_msg = (
                f"Max retries exceeded for fetching organization members for {org_name}"
            )
            logger.exception(error_msg)
            raise RuntimeError(error_msg)
    except GithubException as e:
        logger.warning(f"Could not fetch organization members for {org_name}: {e}")
    return org_members


def _fetch_repository_teams(
    repo: Repository, github_client: Github, retry_count: int = 0
) -> List[TeamInfo]:
    """Fetch teams with access to the repository and their members."""
    teams_data = []
    try:
        logger.info(f"Fetching teams for repository {repo.full_name}")
        teams = repo.get_teams()
        for team in teams:
            team_members = []
            try:
                team_member_objects = team.get_members()
                logger.info(f"Fetching members for team {team_member_objects}")
                for member in team_member_objects:
                    logger.info(
                        f"Processing member {member.login} for team {team.name}"
                    )
                    user_info = UserInfo(
                        login=member.login, name=member.name, email=member.email
                    )
                    team_members.append(user_info)
            except RateLimitExceededException:
                if retry_count < MAX_RETRY_COUNT:
                    sleep_after_rate_limit_exception(github_client)
                    logger.warning(
                        f"Rate limit exceeded while fetching team members for "
                        f"{team.name}. Retrying... (attempt {retry_count + 1}/{MAX_RETRY_COUNT})"
                    )
                    return _fetch_repository_teams(repo, github_client, retry_count + 1)
                else:
                    error_msg = f"Max retries exceeded for fetching team members for {team.name}"
                    logger.exception(error_msg)
                    raise RuntimeError(error_msg)
            except GithubException as e:
                logger.warning(f"Could not fetch team members for {team.name}: {e}")

            team_info = TeamInfo(name=team.name, slug=team.slug, members=team_members)
            teams_data.append(team_info)
    except RateLimitExceededException:
        if retry_count < MAX_RETRY_COUNT:
            sleep_after_rate_limit_exception(github_client)
            logger.warning(
                f"Rate limit exceeded while fetching teams for "
                f"{repo.full_name}. Retrying... (attempt {retry_count + 1}/{MAX_RETRY_COUNT})"
            )
            return _fetch_repository_teams(repo, github_client, retry_count + 1)
        else:
            error_msg = f"Max retries exceeded for fetching teams for {repo.full_name}"
            logger.exception(error_msg)
            raise RuntimeError(error_msg)
    except GithubException as e:
        logger.warning(f"Could not fetch teams: {e}")
    return teams_data


def _categorize_collaborators(
    github_client: Github,
    repo: Repository,
    org_members: List[UserInfo],
    retry_count: int = 0,
) -> tuple[List[UserInfo], List[UserInfo]]:
    """Fetch and categorize collaborators into regular collaborators and outside collaborators."""
    collaborators = []
    outside_collaborators = []

    try:
        logger.info(f"Fetching collaborators for repository {repo.full_name}")
        repo_collaborators = repo.get_collaborators()

        for collaborator in repo_collaborators:
            # For organization repos, check if this is an outside collaborator
            is_outside = False

            if repo.organization:
                try:
                    org = github_client.get_organization(repo.organization.login)
                    is_outside = not org.has_in_members(collaborator)
                except RateLimitExceededException:
                    if retry_count < MAX_RETRY_COUNT:
                        sleep_after_rate_limit_exception(github_client)
                        logger.warning(
                            f"Rate limit exceeded while checking collaborator "
                            f"{collaborator.login}. Retrying... (attempt {retry_count + 1}/{MAX_RETRY_COUNT})"
                        )
                        return _categorize_collaborators(
                            github_client, repo, org_members, retry_count + 1
                        )
                    else:
                        error_msg = f"Max retries exceeded for checking collaborator {collaborator.login}"
                        logger.exception(error_msg)
                        raise RuntimeError(error_msg)
                except GithubException:
                    # If we can't check membership, assume it's a regular collaborator
                    is_outside = False

            collaborator_info = UserInfo(
                login=collaborator.login,
                name=collaborator.name,
                email=collaborator.email,
            )

            # Categorize based on organization membership
            if repo.organization and is_outside:
                outside_collaborators.append(collaborator_info)
            else:
                collaborators.append(collaborator_info)
    except RateLimitExceededException:
        if retry_count < MAX_RETRY_COUNT:
            sleep_after_rate_limit_exception(github_client)
            logger.warning(
                f"Rate limit exceeded while fetching collaborators for "
                f"{repo.full_name}. Retrying... (attempt {retry_count + 1}/{MAX_RETRY_COUNT})"
            )
            return _categorize_collaborators(
                github_client, repo, org_members, retry_count + 1
            )
        else:
            error_msg = (
                f"Max retries exceeded for fetching collaborators for {repo.full_name}"
            )
            logger.exception(error_msg)
            raise RuntimeError(error_msg)

    except GithubException as e:
        logger.warning(f"Could not fetch collaborators: {e}")

    return collaborators, outside_collaborators


def _log_permissions_summary(permissions_data: RepositoryPermissions, repo: Repository):
    """Log a summary of the repository permissions."""
    repo_type = "organization" if repo.organization else "personal"
    logger.info(
        f"Repository permissions summary for {repo.full_name} ({repo_type} repository):"
    )
    logger.info(
        f"  Repository owner: {permissions_data.repository_owner} ({permissions_data.repository_owner_type})"
    )
    if repo.organization:
        logger.info(f"  Organization: {permissions_data.organization_name}")
        logger.info(f"  Organization members: {len(permissions_data.org_members)}")
        logger.info(f"  Teams: {len(permissions_data.teams)}")
        logger.info(
            f"  Outside collaborators: {len(permissions_data.outside_collaborators)}"
        )
    logger.info(f"  Collaborators: {len(permissions_data.collaborators)}")


def _check_repository_visibility(repo: Repository, retry_count: int = 0) -> bool:
    """Check if the repository is public."""
    try:
        return not repo.private
    except RateLimitExceededException as e:
        if retry_count < MAX_RETRY_COUNT:
            logger.warning(
                f"Rate limit exceeded while checking visibility for {repo.full_name}: {e}"
            )
            sleep_after_rate_limit_exception(repo._github)
            return _check_repository_visibility(repo, retry_count + 1)
        else:
            error_msg = (
                f"Max retries exceeded for checking visibility of {repo.full_name}"
            )
            logger.exception(error_msg)
            raise RuntimeError(error_msg)
    except Exception as e:
        logger.warning(
            f"Could not determine repository visibility for {repo.full_name}: {e}"
        )
        return False


def get_repository_permissions(
    github_client: Github, repo: Repository
) -> RepositoryPermissions:
    """
    Get comprehensive repository permissions including organization members, teams,
    collaborators, and outside collaborators with their email addresses.
    Handles both organization and personal repositories.

    Args:
        github_client: Authenticated GitHub client
        repo: Repository object

    Returns:
        RepositoryPermissions object containing permission information
    """
    logger.info(f"Fetching permissions for repository: {repo} {type(repo)}")
    permissions_data = RepositoryPermissions(
        repository_name=repo.full_name,
        repository_id=repo.id,
        repository_owner=repo.owner.login,
        repository_owner_type=repo.owner.type,
        is_public=_check_repository_visibility(repo),
    )
    # If the repository is public, we can skip fetching detailed permissions
    if permissions_data.is_public:
        logger.info(
            f"Repository {repo.full_name} is public, skipping permissions fetch."
        )
        return permissions_data

    try:
        # Check if the repository belongs to an organization
        if repo.organization:
            org_name = repo.organization.login
            permissions_data.organization_name = org_name

            try:
                # Get organization members (including owners)
                permissions_data.org_members = _fetch_organization_members(
                    github_client, org_name
                )

                # Get teams with access to this repository
                permissions_data.teams = _fetch_repository_teams(repo, github_client)

            except GithubException as e:
                logger.warning(f"Could not access organization {org_name}: {e}")
        else:
            # Handle personal repositories by adding owner information
            permissions_data.collaborators = _handle_personal_repository(
                repo, github_client
            )

        # Get direct collaborators (works for both org and personal repos)
        collaborators, outside_collaborators = _categorize_collaborators(
            github_client, repo, permissions_data.org_members
        )

        if repo.organization:
            permissions_data.outside_collaborators.extend(outside_collaborators)

        permissions_data.collaborators.extend(collaborators)

    except Exception as e:
        logger.exception(f"Unexpected error while fetching repository permissions: {e}")

    # Log summary
    _log_permissions_summary(permissions_data, repo)

    return permissions_data


def get_repository_permissions_summary(
    github_client: Github, repo: Repository
) -> RepositoryPermissionsSummary:
    """
    Get a lightweight summary of repository permissions with boolean flags
    indicating presence of members without fetching detailed member information.
    This is more efficient when you only need to know if groups have members.

    Args:
        github_client: Authenticated GitHub client
        repo: Repository object

    Returns:
        RepositoryPermissionsSummary object containing permission flags
    """
    logger.info(f"Fetching permissions summary for repository: {repo.full_name}")
    permissions_summary = RepositoryPermissionsSummary(
        repository_name=repo.full_name,
        repository_id=repo.id,
        repository_owner=repo.owner.login,
        repository_owner_type=repo.owner.type,
        is_public=_check_repository_visibility(repo),
    )

    # If the repository is public, we can skip fetching detailed permissions
    if permissions_summary.is_public:
        logger.info(
            f"Repository {repo.full_name} is public, skipping permissions check."
        )
        return permissions_summary

    try:
        # Check if the repository belongs to an organization
        if repo.organization:
            org_name = repo.organization.login
            permissions_summary.organization_name = org_name

            try:
                # Check if organization has members
                permissions_summary.has_org_members = _check_organization_members_exist(
                    github_client, org_name
                )

                # Check if repository has teams
                (
                    permissions_summary.has_teams,
                    permissions_summary.team_count,
                    permissions_summary.teams,
                ) = _check_repository_teams_exist(repo, github_client)

            except GithubException as e:
                logger.warning(f"Could not access organization {org_name}: {e}")
        else:
            # For personal repositories, there's always at least the owner as collaborator
            permissions_summary.has_collaborators = True

        # Check for direct collaborators (works for both org and personal repos)
        has_collaborators, has_outside_collaborators = _check_collaborators_exist(
            github_client, repo
        )
        logger.info(
            f"Repository {repo.full_name} has collaborators: {has_collaborators}, "
            f"outside collaborators: {has_outside_collaborators}"
        )
        permissions_summary.has_collaborators = (
            permissions_summary.has_collaborators or has_collaborators
        )
        if repo.organization:
            permissions_summary.has_outside_collaborators = has_outside_collaborators

    except Exception as e:
        logger.exception(
            f"Unexpected error while fetching repository permissions summary: {e}"
        )

    # Log summary
    repo_type = "organization" if repo.organization else "personal"
    logger.info(
        f"Repository permissions summary for {repo.full_name} ({repo_type} repository):"
    )
    logger.info(
        f"  Repository owner: {permissions_summary.repository_owner} ({permissions_summary.repository_owner_type})"
    )
    if repo.organization:
        logger.info(f"  Organization: {permissions_summary.organization_name}")
        logger.info(
            f"  Has organization members: {permissions_summary.has_org_members}"
        )
        logger.info(
            f"  Has teams: {permissions_summary.has_teams} (count: {permissions_summary.team_count})"
        )
        if permissions_summary.teams:
            team_names = [
                f"{team.name} ({team.slug})" for team in permissions_summary.teams
            ]
            logger.info(f"  Team details: {', '.join(team_names)}")
        logger.info(
            f"  Has outside collaborators: {permissions_summary.has_outside_collaborators}"
        )
    logger.info(f"  Has collaborators: {permissions_summary.has_collaborators}")

    return permissions_summary


def _check_organization_members_exist(
    github_client: Github, org_name: str, retry_count: int = 0
) -> bool:
    """Check if organization has members without fetching all member details."""
    try:
        logger.info(f"Checking if organization {org_name} has members")
        org = github_client.get_organization(org_name)
        members = org.get_members(filter_="all")
        # Just check if there's at least one member
        try:
            next(iter(members))
            return True
        except StopIteration:
            return False
    except RateLimitExceededException:
        if retry_count < MAX_RETRY_COUNT:
            sleep_after_rate_limit_exception(github_client)
            logger.warning(
                f"Rate limit exceeded while checking organization members for "
                f"{org_name}. Retrying... (attempt {retry_count + 1}/{MAX_RETRY_COUNT})"
            )
            return _check_organization_members_exist(
                github_client, org_name, retry_count + 1
            )
        else:
            error_msg = (
                f"Max retries exceeded for checking organization members for {org_name}"
            )
            logger.exception(error_msg)
            raise RuntimeError(error_msg)
    except GithubException as e:
        logger.warning(f"Could not check organization members for {org_name}: {e}")
        return False


def _check_repository_teams_exist(
    repo: Repository, github_client: Github, retry_count: int = 0
) -> tuple[bool, int, List[TeamInfo]]:
    """Check if repository has teams and return team names/slugs without fetching team member details."""
    try:
        logger.info(f"Checking teams for repository {repo.full_name}")
        teams = repo.get_teams()
        team_count = 0
        has_teams = False
        team_infos = []

        try:
            # Get team info without fetching members
            for team in teams:
                team_count += 1
                has_teams = True
                team_info = TeamInfo(
                    name=team.name,
                    slug=team.slug,
                    members=[],  # Empty list since we're not fetching members for summary
                )
                team_infos.append(team_info)
        except StopIteration:
            pass

        return has_teams, team_count, team_infos
    except RateLimitExceededException:
        if retry_count < MAX_RETRY_COUNT:
            sleep_after_rate_limit_exception(github_client)
            logger.warning(
                f"Rate limit exceeded while checking teams for "
                f"{repo.full_name}. Retrying... (attempt {retry_count + 1}/{MAX_RETRY_COUNT})"
            )
            return _check_repository_teams_exist(repo, github_client, retry_count + 1)
        else:
            error_msg = f"Max retries exceeded for checking teams for {repo.full_name}"
            logger.exception(error_msg)
            raise RuntimeError(error_msg)
    except GithubException as e:
        logger.warning(f"Could not check teams: {e}")
        return False, 0, []


def _check_collaborators_exist(
    github_client: Github, repo: Repository, retry_count: int = 0
) -> tuple[bool, bool]:
    """Check if repository has collaborators and outside collaborators without fetching details."""
    has_collaborators = False
    has_outside_collaborators = False

    try:
        logger.info(f"Checking collaborators for repository {repo.full_name}")
        repo_collaborators = repo.get_collaborators()
        logger.info(
            f"Found {repo_collaborators.totalCount} collaborators for {repo.full_name}"
        )
        for collaborator in repo_collaborators:
            has_collaborators = True

            # For organization repos, check if this is an outside collaborator
            if repo.organization:
                try:
                    org = github_client.get_organization(repo.organization.login)
                    is_outside = not org.has_in_members(collaborator)
                    if is_outside:
                        has_outside_collaborators = True
                        # If we found both types, we can break early
                        if has_collaborators and has_outside_collaborators:
                            break
                except RateLimitExceededException:
                    if retry_count < MAX_RETRY_COUNT:
                        sleep_after_rate_limit_exception(github_client)
                        logger.warning(
                            f"Rate limit exceeded while checking collaborator "
                            f"{collaborator.login}. Retrying... (attempt {retry_count + 1}/{MAX_RETRY_COUNT})"
                        )
                        return _check_collaborators_exist(
                            github_client, repo, retry_count + 1
                        )
                    else:
                        error_msg = f"Max retries exceeded for checking collaborator {collaborator.login}"
                        logger.exception(error_msg)
                        raise RuntimeError(error_msg)
                except GithubException:
                    # If we can't check membership, assume it's a regular collaborator
                    pass
            else:
                # For personal repos, break after finding first collaborator
                break

    except RateLimitExceededException:
        if retry_count < MAX_RETRY_COUNT:
            sleep_after_rate_limit_exception(github_client)
            logger.warning(
                f"Rate limit exceeded while checking collaborators for "
                f"{repo.full_name}. Retrying... (attempt {retry_count + 1}/{MAX_RETRY_COUNT})"
            )
            return _check_collaborators_exist(github_client, repo, retry_count + 1)
        else:
            error_msg = (
                f"Max retries exceeded for checking collaborators for {repo.full_name}"
            )
            logger.exception(error_msg)
            raise RuntimeError(error_msg)
    except GithubException as e:
        logger.warning(f"Could not check collaborators: {e}")

    return has_collaborators, has_outside_collaborators


def _handle_personal_repository(
    repo: Repository, github_client: Github
) -> List[UserInfo]:
    """Handle personal repositories by adding owner information."""
    try:
        owner_info = UserInfo(
            login=repo.owner.login,
            name=repo.owner.name,
            email=repo.owner.email,
        )
        return [owner_info]
    except Exception as e:
        logger.warning(f"Could not fetch owner information for {repo.full_name}: {e}")
        return []
