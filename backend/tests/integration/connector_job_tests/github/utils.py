from typing import Optional

from github import Github
from github.GithubException import GithubException

from onyx.utils.logger import setup_logger

logger = setup_logger()


class GitHubManager:
    """
    Manager class for GitHub operations used in testing.
    Provides methods to change repository visibility, check repository visibility, and manage teams.
    """

    def __init__(self, github_client: Github):
        """
        Initialize the GitHub manager with a GitHub client.

        Args:
            github_client: Authenticated GitHub client instance
        """
        self.github_client = github_client

    def change_repository_visibility(
        self, repo_owner: str, repo_name: str, visibility: str
    ) -> bool:
        """
        Change the visibility of a repository.

        Args:
            repo_owner: Repository owner (organization or username)
            repo_name: Repository name
            visibility: New visibility ('public', 'private', or 'internal')

        Returns:
            bool: True if successful, False otherwise

        Raises:
            ValueError: If visibility is not valid
            GithubException: If GitHub API call fails
        """
        if visibility not in ["public", "private", "internal"]:
            raise ValueError(
                f"Invalid visibility: {visibility}. Must be 'public', 'private', or 'internal'"
            )

        try:
            repo = self.github_client.get_repo(f"{repo_owner}/{repo_name}")

            # Check if we have admin permissions
            if not repo.permissions.admin:
                logger.error(
                    f"No admin permissions for repository {repo_owner}/{repo_name}"
                )
                return False

            # # Change visibility
            # repo.edit(private=(visibility == "private"))

            # Note: Internal repositories are only available for GitHub Enterprise
            try:
                repo.edit(visibility=visibility)
            except GithubException as e:
                logger.warning(f"Could not set repository to {visibility}: {e}")
                return False

            logger.info(
                f"Successfully changed {repo_owner}/{repo_name} visibility to {visibility}"
            )
            return True

        except GithubException as e:
            logger.error(f"Failed to change repository visibility: {e}")
            return False

    def add_team_to_repository(
        self, repo_owner: str, repo_name: str, team_slug: str, permission: str = "push"
    ) -> bool:
        """
        Add a team to a repository with specified permissions.

        Args:
            repo_owner: Repository owner (organization)
            repo_name: Repository name
            team_slug: Team slug (not team name)
            permission: Permission level ('pull', 'push', 'admin', 'maintain', 'triage')

        Returns:
            bool: True if successful, False otherwise

        Raises:
            GithubException: If GitHub API call fails
        """
        valid_permissions = ["pull", "push", "admin", "maintain", "triage"]
        if permission not in valid_permissions:
            raise ValueError(
                f"Invalid permission: {permission}. Must be one of {valid_permissions}"
            )

        try:
            repo = self.github_client.get_repo(f"{repo_owner}/{repo_name}")
            org = self.github_client.get_organization(repo_owner)
            team = org.get_team_by_slug(team_slug)

            # Add team to repository
            team.add_to_repos(repo)

            # Set team permissions on the repository
            team.set_repo_permission(repo, permission)

            logger.info(
                f"Successfully added team {team_slug} to {repo_owner}/{repo_name} with {permission} permissions"
            )
            return True

        except GithubException as e:
            logger.error(f"Failed to add team to repository: {e}")
            return False

    def remove_team_from_repository(
        self, repo_owner: str, repo_name: str, team_slug: str
    ) -> bool:
        """
        Remove a team from a repository.

        Args:
            repo_owner: Repository owner (organization)
            repo_name: Repository name
            team_slug: Team slug (not team name)

        Returns:
            bool: True if successful, False otherwise

        Raises:
            GithubException: If GitHub API call fails
        """
        try:
            repo = self.github_client.get_repo(f"{repo_owner}/{repo_name}")
            org = self.github_client.get_organization(repo_owner)
            team = org.get_team_by_slug(team_slug)

            # Remove team from repository
            team.remove_from_repos(repo)

            logger.info(
                f"Successfully removed team {team_slug} from {repo_owner}/{repo_name}"
            )
            return True

        except GithubException as e:
            logger.error(f"Failed to remove team from repository: {e}")
            return False

    def get_repository_visibility(
        self, repo_owner: str, repo_name: str
    ) -> Optional[str]:
        """
        Get the current visibility of a repository.

        Args:
            repo_owner: Repository owner
            repo_name: Repository name

        Returns:
            Optional[str]: Repository visibility ('public', 'private', 'internal') or None if failed
        """
        try:
            repo = self.github_client.get_repo(f"{repo_owner}/{repo_name}")

            if hasattr(repo, "visibility"):
                return repo.visibility
            else:
                # Fallback for older GitHub API versions
                return "private" if repo.private else "public"

        except GithubException as e:
            logger.error(f"Failed to get repository visibility: {e}")
            return None
