from github import Github
from github.Repository import Repository

from ee.onyx.external_permissions.github.utils import get_repository_permissions_summary
from ee.onyx.external_permissions.github.utils import RepositoryPermissionsSummary
from onyx.access.models import ExternalAccess
from onyx.utils.logger import setup_logger

logger = setup_logger()


def get_external_access_permission(
    repo: Repository, github_client: Github
) -> ExternalAccess:
    """
    Get the external access permission for a repository.
    """
    user_emails: list[str] = []
    group_ids: list[str] = []

    repo_permissions: RepositoryPermissionsSummary = get_repository_permissions_summary(
        github_client, repo
    )

    if repo_permissions.is_public:
        return ExternalAccess(
            external_user_emails=user_emails,
            external_user_group_ids=group_ids,
            is_public=True,
        )

    # We maintain collaborators, owners, and outside collaborators as three separate groups
    # instead of adding individual user emails to ExternalAccess.external_user_emails for two reasons:
    # 1. Changes in repo collaborators (additions/removals) would require updating all documents.
    # 2. Repo permissions can change without updating the repo's updated_at timestamp,
    #    forcing full permission syncs for all documents every time, which is inefficient.
    group_ids.extend(
        [repo_permissions.collaborators_group_id, repo_permissions.owners_group_id]
    )

    if repo_permissions.has_outside_collaborators:
        group_ids.append(repo_permissions.outside_collaborators_group_id)

    if repo_permissions.has_teams:
        group_ids.extend(team.slug for team in repo_permissions.teams if team.slug)

    logger.info(group_ids)
    return ExternalAccess(
        external_user_emails=user_emails,
        external_user_group_ids=group_ids,
        is_public=False,
    )
