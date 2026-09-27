import json
from collections.abc import Generator

from github.Repository import Repository

from ee.onyx.external_permissions.github.utils import (
    GitHubVisibility,
    form_collaborators_group_id,
    form_organization_group_id,
    get_external_access_permission,
    get_repository_visibility,
)
from ee.onyx.external_permissions.perm_sync_types import (
    FetchAllDocumentsFunction,
    FetchAllDocumentsIdsFunction,
)
from ee.onyx.external_permissions.utils import credential_json
from onyx.access.models import DocExternalAccess
from onyx.access.utils import build_ext_group_name_for_onyx
from onyx.configs.constants import DocumentSource
from onyx.connectors.github.connector import DocMetadata, GithubConnector
from onyx.db.models import ConnectorCredentialPair
from onyx.db.utils import DocumentRow, SortOrder
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
    """Update document permissions when repository visibility changes."""
    logger.info("Starting GitHub document sync for CC pair ID: %s", cc_pair.id)

    # Initialize GitHub connector with credentials
    github_connector: GithubConnector = GithubConnector(
        **cc_pair.connector.connector_specific_config
    )

    github_connector.load_credentials(credential_json(cc_pair))
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
            visibility_changed = _is_repo_visibility_changed_from_groups(
                repo=repo,
                current_external_group_ids=current_external_group_ids,
            )

            if visibility_changed:
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
