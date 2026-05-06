import json
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
from ee.onyx.external_permissions.perm_sync_types import FetchAllDocumentsIdsFunction
from onyx.access.models import DocExternalAccess
from onyx.access.utils import build_ext_group_name_for_onyx
from onyx.configs.constants import DocumentSource
from onyx.connectors.github.connector import DocMetadata
from onyx.connectors.github.connector import GithubConnector
from onyx.db.models import ConnectorCredentialPair
from onyx.db.utils import DocumentRow
from onyx.db.utils import SortOrder
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()

GITHUB_DOC_SYNC_LABEL = "github_doc_sync"


def github_doc_sync(
    cc_pair: ConnectorCredentialPair,
    fetch_all_existing_docs_fn: FetchAllDocumentsFunction,
    fetch_all_existing_docs_ids_fn: FetchAllDocumentsIdsFunction,  # noqa: ARG001
    callback: IndexingHeartbeatInterface | None = None,
) -> Generator[DocExternalAccess, None, None]:
    """
    Sync GitHub documents with external access permissions.

    This function checks each repository for visibility/team changes and updates
    document permissions accordingly without using checkpoints.
    """
    logger.info("Starting GitHub document sync for CC pair ID: %s", cc_pair.id)

    # Initialize GitHub connector with credentials
    github_connector: GithubConnector = GithubConnector(
        **cc_pair.connector.connector_specific_config
    )

    credential_json = (
        cc_pair.credential.credential_json.get_value(apply_mask=False)
        if cc_pair.credential.credential_json
        else {}
    )
    github_connector.load_credentials(credential_json)
    logger.info("GitHub connector credentials loaded successfully")

    if not github_connector.github_client:
        logger.error("GitHub client initialization failed")
        raise ValueError("github_client is required")

    # Get all repositories from GitHub API
    logger.info("Fetching all repositories from GitHub API")
    try:
        repos = github_connector.fetch_configured_repos()

        logger.info("Found %s repositories to check", len(repos))
    except Exception as e:
        logger.error("Failed to fetch repositories: %s", e)
        raise

    repo_to_doc_list_map: dict[str, list[DocumentRow]] = {}
    # sort order is ascending because we want to get the oldest documents first
    existing_docs: list[DocumentRow] = fetch_all_existing_docs_fn(
        sort_order=SortOrder.ASC
    )
    logger.info("Found %s documents to check", len(existing_docs))
    for doc in existing_docs:
        try:
            doc_metadata = DocMetadata.model_validate_json(json.dumps(doc.doc_metadata))
            if doc_metadata.repo not in repo_to_doc_list_map:
                repo_to_doc_list_map[doc_metadata.repo] = []
            repo_to_doc_list_map[doc_metadata.repo].append(doc)
        except Exception as e:
            logger.error("Failed to parse doc metadata: %s for doc %s", e, doc.id)
            continue
    logger.info("Found %s documents to check", len(repo_to_doc_list_map))
    # Process each repository individually
    for repo in repos:
        try:
            logger.info("Processing repository: %s (name: %s)", repo.id, repo.name)
            repo_doc_list: list[DocumentRow] = repo_to_doc_list_map.get(
                repo.full_name, []
            )
            if not repo_doc_list:
                logger.warning(
                    "No documents found for repository %s (%s)", repo.id, repo.name
                )
                continue

            current_external_group_ids = repo_doc_list[0].external_user_group_ids or []
            # Check if repository has any permission changes
            has_changes = _check_repository_for_changes(
                repo=repo,
                github_client=github_connector.github_client,
                current_external_group_ids=current_external_group_ids,
            )

            if has_changes:
                logger.info(
                    "Repository %s (%s) has changes, updating documents",
                    repo.id,
                    repo.name,
                )

                # Get new external access permissions for this repository
                new_external_access = get_external_access_permission(
                    repo, github_connector.github_client
                )

                logger.info(
                    "Found %s documents for repository %s",
                    len(repo_doc_list),
                    repo.full_name,
                )

                # Yield updated external access for each document
                for doc in repo_doc_list:
                    if callback:
                        callback.progress(GITHUB_DOC_SYNC_LABEL, 1)

                    yield DocExternalAccess(
                        doc_id=doc.id,
                        external_access=new_external_access,
                    )
            else:
                logger.info(
                    "Repository %s (%s) has no changes, skipping", repo.id, repo.name
                )
        except Exception as e:
            logger.error(
                "Error processing repository %s (%s): %s", repo.id, repo.name, e
            )

    logger.info("GitHub document sync completed for CC pair ID: %s", cc_pair.id)


def _check_repository_for_changes(
    repo: Repository,
    github_client: Github,
    current_external_group_ids: list[str],
) -> bool:
    """
    Check if repository has any permission changes (visibility or team updates).
    """
    logger.info("Checking repository %s (%s) for changes", repo.id, repo.name)

    # Check for repository visibility changes using the sample document data
    if _is_repo_visibility_changed_from_groups(
        repo=repo,
        current_external_group_ids=current_external_group_ids,
    ):
        logger.info("Repository %s (%s) has visibility changes", repo.id, repo.name)
        return True

    # Check for team membership changes if repository is private
    if get_repository_visibility(
        repo
    ) == GitHubVisibility.PRIVATE and _teams_updated_from_groups(
        repo=repo,
        github_client=github_client,
        current_external_group_ids=current_external_group_ids,
    ):
        logger.info("Repository %s (%s) has team changes", repo.id, repo.name)
        return True

    logger.info("Repository %s (%s) has no changes", repo.id, repo.name)
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
    logger.info("Current repository visibility: %s", current_repo_visibility.value)

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

    logger.info("Inferred existing visibility: %s", existing_repo_visibility.value)

    visibility_changed = existing_repo_visibility != current_repo_visibility
    if visibility_changed:
        logger.info(
            "Visibility changed for repo %s (%s): %s -> %s",
            repo.id,
            repo.name,
            existing_repo_visibility.value,
            current_repo_visibility.value,
        )

    return visibility_changed


def _teams_updated_from_groups(
    repo: Repository,
    github_client: Github,
    current_external_group_ids: list[str],
) -> bool:
    """
    Check if repository team memberships have changed using existing group IDs.
    """
    # Fetch current team slugs for the repository
    current_teams = fetch_repository_team_slugs(repo=repo, github_client=github_client)
    logger.info(
        "Current teams for repository %s (name: %s): %s",
        repo.id,
        repo.name,
        current_teams,
    )

    # Build group IDs to exclude from team comparison (non-team groups)
    collaborators_group_id = build_ext_group_name_for_onyx(
        source=DocumentSource.GITHUB,
        ext_group_name=form_collaborators_group_id(repo.id),
    )
    outside_collaborators_group_id = build_ext_group_name_for_onyx(
        source=DocumentSource.GITHUB,
        ext_group_name=form_outside_collaborators_group_id(repo.id),
    )
    non_team_group_ids = {collaborators_group_id, outside_collaborators_group_id}

    # Extract existing team IDs from current external group IDs
    existing_team_ids = set()
    for group_id in current_external_group_ids:
        # Skip all non-team groups, keep only team groups
        if group_id not in non_team_group_ids:
            existing_team_ids.add(group_id)

    # Note: existing_team_ids from DB are already prefixed (e.g., "github__team-slug")
    # but current_teams from API are raw team slugs, so we need to add the prefix
    current_team_ids = set()
    for team_slug in current_teams:
        team_group_id = build_ext_group_name_for_onyx(
            source=DocumentSource.GITHUB,
            ext_group_name=team_slug,
        )
        current_team_ids.add(team_group_id)

    logger.info(
        "Existing team IDs: %s, Current team IDs: %s",
        existing_team_ids,
        current_team_ids,
    )

    # Compare actual team IDs to detect changes
    teams_changed = current_team_ids != existing_team_ids
    if teams_changed:
        logger.info(
            "Team changes detected for repo %s (name: %s): existing=%s, current=%s",
            repo.id,
            repo.name,
            existing_team_ids,
            current_team_ids,
        )

    return teams_changed
