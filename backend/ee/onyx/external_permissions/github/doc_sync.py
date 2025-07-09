from collections.abc import Generator

from github import Github
from github.Repository import Repository

from ee.onyx.external_permissions.github.utils import fetch_repository_team_slugs
from ee.onyx.external_permissions.github.utils import form_collaborators_group_id
from ee.onyx.external_permissions.github.utils import form_organization_group_id
from ee.onyx.external_permissions.github.utils import (
    form_outside_collaborators_group_id,
)
from ee.onyx.external_permissions.github.utils import get_external_access_permission
from ee.onyx.external_permissions.github.utils import get_repository_visibility
from ee.onyx.external_permissions.github.utils import GitHubVisibility
from ee.onyx.external_permissions.perm_sync_types import FetchAllDocumentsFunction
from onyx.access.models import DocExternalAccess
from onyx.access.utils import build_ext_group_name_for_onyx
from onyx.configs.constants import DocumentSource
from onyx.connectors.github.connector import GithubConnector
from onyx.db.models import ConnectorCredentialPair
from onyx.db.utils import DocumentFilter
from onyx.db.utils import FilterOperation
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()

GITHUB_DOC_SYNC_LABEL = "github_doc_sync"


def github_doc_sync(
    cc_pair: ConnectorCredentialPair,
    fetch_all_existing_docs_fn: FetchAllDocumentsFunction,
    callback: IndexingHeartbeatInterface | None = None,
) -> Generator[DocExternalAccess, None, None]:
    """
    Sync GitHub documents with external access permissions.

    This function checks each repository for visibility/team changes and updates
    document permissions accordingly without using checkpoints.

    Args:
        cc_pair: Connector credential pair for GitHub authentication
        fetch_all_existing_docs_fn: Function to fetch existing documents
        callback: Indexing heartbeat interface for progress tracking

    Yields:
        DocExternalAccess: Document external access records for updated documents
    """
    logger.info(f"Starting GitHub document sync for CC pair ID: {cc_pair.id}")

    # Initialize GitHub connector with credentials
    github_connector: GithubConnector = GithubConnector(
        **cc_pair.connector.connector_specific_config
    )

    github_connector.load_credentials(cc_pair.credential.credential_json)
    logger.info("GitHub connector credentials loaded successfully")

    if not github_connector.github_client:
        logger.error("GitHub client initialization failed")
        raise ValueError("github_client is required")

    # Get all repositories from GitHub API
    logger.info("Fetching all repositories from GitHub API")
    try:
        repos = []
        if github_connector.repositories:
            if "," in github_connector.repositories:
                # Multiple repositories specified
                repos = github_connector.get_github_repos(
                    github_connector.github_client
                )
            else:
                # Single repository
                repos = [
                    github_connector.get_github_repo(github_connector.github_client)
                ]
        else:
            # All repositories
            repos = github_connector.get_all_repos(github_connector.github_client)

        logger.info(f"Found {len(repos)} repositories to check")
    except Exception as e:
        logger.error(f"Failed to fetch repositories: {e}")
        raise

    # Process each repository individually
    for repo in repos:

        logger.info(f"Processing repository: {repo.id} (name: {repo.name})")

        # Check if repository has any permission changes
        has_changes = _check_repository_for_changes(
            repo=repo,
            github_client=github_connector.github_client,
            fetch_all_existing_docs_fn=fetch_all_existing_docs_fn,
        )

        if has_changes:
            logger.info(
                f"Repository {repo.id} ({repo.name}) has changes, updating documents"
            )

            # Get new external access permissions for this repository
            new_external_access = get_external_access_permission(
                repo, github_connector.github_client
            )

            repo_documents = fetch_all_existing_docs_fn(
                columns=["id"],
                document_filter=DocumentFilter(
                    field="id",
                    operation=FilterOperation.LIKE,
                    value=f"%{repo.full_name}%",
                ),
            )

            logger.info(
                f"Found {len(repo_documents)} documents for repository {repo.full_name}"
            )

            # Yield updated external access for each document
            for doc in repo_documents:
                if callback:
                    callback.progress(GITHUB_DOC_SYNC_LABEL, 1)

                yield DocExternalAccess(
                    doc_id=doc["id"],
                    external_access=new_external_access,
                )
        else:
            logger.info(f"Repository {repo.id} ({repo.name}) has no changes, skipping")

    logger.info(f"GitHub document sync completed for CC pair ID: {cc_pair.id}")


def _check_repository_for_changes(
    repo: Repository,
    github_client: Github,
    fetch_all_existing_docs_fn: FetchAllDocumentsFunction,
) -> bool:
    """
    Check if repository has any permission changes (visibility or team updates).

    Optimized to use a single database query and reuse the data for all checks.

    Args:
        repo: GitHub repository object
        github_client: GitHub client instance
        fetch_all_existing_docs_fn: Function to fetch existing documents

    Returns:
        True if repository has changes that require document permission updates
    """
    logger.info(f"Checking repository {repo.id} ({repo.name}) for changes")

    docs = fetch_all_existing_docs_fn(
        columns=["id", "external_user_group_ids"],
        document_filter=DocumentFilter(
            field="id",
            operation=FilterOperation.LIKE,
            value=f"%{repo.full_name}%",
        ),
        limit=1,
    )

    # If no documents exist for this connector/credential pair, no changes to process
    if not docs:
        logger.info(f"No documents found for repository {repo.id} ({repo.name})")
        return False

    doc = docs[0]
    current_external_group_ids = doc.get("external_user_group_ids", []) or []

    # Check for repository visibility changes using the sample document data
    if _is_repo_visibility_changed_from_groups(
        repo=repo,
        current_external_group_ids=current_external_group_ids,
    ):
        logger.info(f"Repository {repo.id} ({repo.name}) has visibility changes")
        return True

    # Check for team membership changes if repository is private
    if get_repository_visibility(
        repo
    ) == GitHubVisibility.PRIVATE and _teams_updated_from_groups(
        repo=repo,
        github_client=github_client,
        current_external_group_ids=current_external_group_ids,
    ):
        logger.info(f"Repository {repo.id} ({repo.name}) has team changes")
        return True

    logger.info(f"Repository {repo.id} ({repo.name}) has no changes")
    return False


def _is_repo_visibility_changed_from_groups(
    repo: Repository,
    current_external_group_ids: list[str],
) -> bool:
    """
    Check if repository visibility has changed by analyzing existing external group IDs.

    Args:
        repo: GitHub repository object
        current_external_group_ids: List of external group IDs from existing document

    Returns:
        True if visibility has changed
    """
    current_repo_visibility = get_repository_visibility(repo)
    logger.info(f"Current repository visibility: {current_repo_visibility.value}")

    # Build expected group IDs for current visibility
    collaborators_group_id = build_ext_group_name_for_onyx(
        source=DocumentSource.GITHUB,
        ext_group_name=form_collaborators_group_id(repo.id),
    )

    org_group_id = None
    if repo.organization:
        org_group_id = build_ext_group_name_for_onyx(
            source=DocumentSource.GITHUB,
            ext_group_name=form_organization_group_id(repo.organization.id),
        )

    # Determine existing visibility from group IDs
    has_collaborators_group = collaborators_group_id in current_external_group_ids
    has_org_group = org_group_id and org_group_id in current_external_group_ids

    if has_collaborators_group:
        existing_repo_visibility = GitHubVisibility.PRIVATE
    elif has_org_group:
        existing_repo_visibility = GitHubVisibility.INTERNAL
    else:
        existing_repo_visibility = GitHubVisibility.PUBLIC

    logger.info(f"Inferred existing visibility: {existing_repo_visibility.value}")

    visibility_changed = existing_repo_visibility != current_repo_visibility
    if visibility_changed:
        logger.info(
            f"Visibility changed for repo {repo.id} ({repo.name}): "
            f"{existing_repo_visibility.value} -> {current_repo_visibility.value}"
        )

    return visibility_changed


def _teams_updated_from_groups(
    repo: Repository,
    github_client: Github,
    current_external_group_ids: list[str],
) -> bool:
    """
    Check if repository team memberships have changed using existing group IDs.

    Args:
        repo: GitHub repository object
        github_client: GitHub client instance
        current_external_group_ids: List of external group IDs from existing document

    Returns:
        True if team count differs from existing groups
    """
    # Fetch current team slugs for the repository
    current_teams = fetch_repository_team_slugs(repo=repo, github_client=github_client)
    logger.info(
        f"Current teams for repository {repo.id} (name: {repo.name}): {current_teams}"
    )

    # Build group IDs to exclude from team count
    collaborators_group_id = build_ext_group_name_for_onyx(
        source=DocumentSource.GITHUB,
        ext_group_name=form_collaborators_group_id(repo.id),
    )
    outside_collaborators_group_id = build_ext_group_name_for_onyx(
        source=DocumentSource.GITHUB,
        ext_group_name=form_outside_collaborators_group_id(repo.id),
    )

    # Extract existing team IDs from current external group IDs
    existing_team_ids = set()
    for group_id in current_external_group_ids:
        # Skip collaborators and outside collaborators groups, focus on team groups
        if group_id not in [collaborators_group_id, outside_collaborators_group_id]:
            existing_team_ids.add(group_id)

    logger.info(
        f"Existing team IDs: {existing_team_ids}, Current teams: {current_teams}"
    )

    # Compare team counts to detect changes
    teams_changed = len(current_teams) != len(existing_team_ids)
    if teams_changed:
        logger.info(
            f"Team count changed for repo {repo.id} (name: {repo.name}): "
            f"{len(existing_team_ids)} -> {len(current_teams)}"
        )

    return teams_changed
