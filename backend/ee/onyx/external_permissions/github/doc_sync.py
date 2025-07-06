from collections.abc import Generator
from datetime import datetime
from datetime import timezone

from github import Github
from github.Repository import Repository

from ee.onyx.external_permissions.github.utils import fetch_repository_team_slugs
from ee.onyx.external_permissions.github.utils import form_collaborators_group_id
from ee.onyx.external_permissions.github.utils import form_organization_group_id
from ee.onyx.external_permissions.github.utils import (
    form_outside_collaborators_group_id,
)
from ee.onyx.external_permissions.github.utils import get_repository_visibility
from ee.onyx.external_permissions.perm_sync_types import FetchAllDocumentsFunction
from onyx.access.models import DocExternalAccess
from onyx.access.utils import build_ext_group_name_for_onyx
from onyx.configs.constants import DocumentSource
from onyx.connectors.connector_runner import SlimCheckpointOutputWrapper
from onyx.connectors.github.connector import GithubConnector
from onyx.connectors.github.connector import GithubConnectorCheckpoint
from onyx.connectors.github.models import SerializedRepository
from onyx.connectors.github.utils import deserialize_repository
from onyx.connectors.interfaces import CheckpointedSlimConnector
from onyx.connectors.models import SlimDocument
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Document
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

    Args:
        cc_pair: Connector credential pair for GitHub authentication
        fetch_all_existing_docs_fn: Function to fetch existing documents
        callback: Indexing heartbeat interface for progress tracking

    Yields:
        DocExternalAccess: Document external access records
    """

    # Initialize GitHub connector with credentials
    logger.info(f"Initializing GitHub connector for credential pair ID: {cc_pair.id}")
    github_connector: GithubConnector = GithubConnector(
        **cc_pair.connector.connector_specific_config
    )

    github_connector.load_credentials(cc_pair.credential.credential_json)
    logger.info("GitHub connector credentials loaded successfully")

    if not github_connector.github_client:
        logger.error("GitHub client initialization failed")
        raise ValueError("github_client is required")

    if not isinstance(github_connector, CheckpointedSlimConnector):
        logger.error(f"Invalid connector type: {type(github_connector)}")
        raise TypeError(
            f"Expected CheckpointedSlimConnector, got {type(github_connector)}"
        )

    logger.info("Starting GitHub document sync with checkpointed retrieval")

    # Initialize checkpoint and time boundaries for document retrieval
    checkpoint = github_connector.build_dummy_checkpoint()
    current_time = datetime.now(timezone.utc)
    start_time = 0.0  # Start from epoch time to get all documents
    logger.info(
        f"Checkpoint initialized: {checkpoint}, time range: {start_time} to {current_time.timestamp()}"
    )

    # Process documents in batches using checkpointing
    while checkpoint.has_more:
        # Check for stop signal before processing each batch
        if callback:
            if callback.should_stop():
                raise RuntimeError(f"{GITHUB_DOC_SYNC_LABEL}: Stop signal detected")

        logger.info(f"Processing checkpoint batch, has_more: {checkpoint.has_more}")
        slim_doc_generator = github_connector.checkpointed_retrieve_all_slim_documents(
            start=start_time,
            end=current_time.timestamp(),
            checkpoint=checkpoint,
        )

        for slim_doc, failure, new_checkpoint in SlimCheckpointOutputWrapper[
            GithubConnectorCheckpoint
        ]()(slim_doc_generator):
            # Check for stop signal before processing each document
            if callback:
                if callback.should_stop():
                    raise RuntimeError(f"{GITHUB_DOC_SYNC_LABEL}: Stop signal detected")

            # New checkpoint means we've moved to a different repository
            if new_checkpoint:
                logger.info(f"Received new checkpoint: {new_checkpoint}")
                checkpoint = new_checkpoint

                # Process repository visibility and team changes if checkpoint has cached repo
                if checkpoint.has_more and checkpoint.cached_repo:
                    repo: Repository = deserialize_repository(
                        checkpoint.cached_repo, github_connector.github_client
                    )
                    logger.info(
                        f"Processing cached repository: {repo.id} (name: {repo.name})"
                    )

                    checkpoint = _check_repo_permission_changes(
                        repo=repo,
                        github_client=github_connector.github_client,
                        fetch_all_existing_docs_fn=fetch_all_existing_docs_fn,
                        checkpoint=checkpoint,
                        callback=callback,
                    )
                    continue
                else:
                    logger.info("No cached repository or no more data, continuing")
                    continue

            # Yield document external access records
            if slim_doc and slim_doc.external_access:
                if isinstance(slim_doc, SlimDocument):
                    # Report progress for each document processed
                    if callback:
                        callback.progress(GITHUB_DOC_SYNC_LABEL, 1)

                    yield DocExternalAccess(
                        doc_id=slim_doc.id,
                        external_access=slim_doc.external_access,
                    )


def _check_repo_permission_changes(
    repo: Repository,
    github_client: Github,
    fetch_all_existing_docs_fn: FetchAllDocumentsFunction,
    checkpoint: GithubConnectorCheckpoint,
    callback: IndexingHeartbeatInterface | None = None,
) -> GithubConnectorCheckpoint:
    """
    Check if repository has any permission changes (visibility or team updates).

    Returns:
        Updated checkpoint with next repository to process
    """
    # Check for stop signal before processing repository
    if callback:
        if callback.should_stop():
            raise RuntimeError(f"{GITHUB_DOC_SYNC_LABEL}: Stop signal detected")

    # Check for repository visibility changes, if it's changed,
    # we need to re-sync the repository permissions for all documents in the repository
    if is_repo_visibility_changed(
        repo=repo,
        github_client=github_client,
        fetch_all_existing_docs_fn=fetch_all_existing_docs_fn,
    ):
        logger.info(
            f"Repository {repo.id} (name: {repo.name}) visibility has changed, continuing to next batch"
        )
        return checkpoint

    # Check for team membership changes, if it's changed,
    # we need to re-sync the repository permissions for all documents in the repository
    if get_repository_visibility(repo) == "private" and _teams_updated(
        repo, github_client, fetch_all_existing_docs_fn
    ):
        logger.info(
            f"Teams updated for repository {repo.id} (name: {repo.name}), returning checkpoint"
        )
        return checkpoint

    # If no changes, move to next repository in the checkpoint and do the same check
    if checkpoint.cached_repo_ids:
        next_id = checkpoint.cached_repo_ids.pop()
        logger.info(f"Moving to next cached repository: {next_id}")
        next_repo = github_client.get_repo(next_id)
        logger.info(f"Next repository: {next_id} (name: {next_repo.name})")
        repo = next_repo
        checkpoint.cached_repo = SerializedRepository(
            id=next_id,
            headers=next_repo.raw_headers,
            raw_data=next_repo.raw_data,
        )
        return _check_repo_permission_changes(
            repo=repo,
            github_client=github_client,
            fetch_all_existing_docs_fn=fetch_all_existing_docs_fn,
            checkpoint=checkpoint,
            callback=callback,
        )

    # If no more repositories to process, return the checkpoint
    logger.info("No more repositories to process, marking checkpoint as complete")
    checkpoint.has_more = False
    checkpoint.cached_repo = None
    return checkpoint


def _teams_updated(
    repo: Repository,
    github_client: Github,
    fetch_all_existing_docs_fn: FetchAllDocumentsFunction,
) -> bool:
    """
    Check if repository team memberships have changed.

    Returns:
        True if team count differs from existing documents
    """
    # Fetch current team slugs for the repository
    current_teams = fetch_repository_team_slugs(repo=repo, github_client=github_client)
    logger.info(
        f"Current teams for repository {repo.id} (name: {repo.name}): {current_teams}"
    )

    # Build collaborators group ID for comparison
    collaborators_group_id = form_collaborators_group_id(repo.id)
    onyx_collaborators_group_id = build_ext_group_name_for_onyx(
        source=DocumentSource.GITHUB, ext_group_name=collaborators_group_id
    )

    # Fetch existing documents with collaborators group
    existing_docs = fetch_all_existing_docs_fn(
        columns=[Document.id, Document.external_user_group_ids],
        where_clause=Document.external_user_group_ids.contains(
            [onyx_collaborators_group_id]
        ),
        limit=1,
    )
    logger.info(f"Found {len(existing_docs)} existing docs with collaborators group")

    # Extract existing team IDs from documents
    existing_team_ids = set()
    for doc in existing_docs:
        if doc.get("external_user_group_ids"):
            for group_id in doc["external_user_group_ids"]:
                # Skip collaborators and outside collaborators groups, focus on team groups
                if group_id not in [
                    onyx_collaborators_group_id,
                    build_ext_group_name_for_onyx(
                        source=DocumentSource.GITHUB,
                        ext_group_name=form_outside_collaborators_group_id(repo.id),
                    ),
                ]:
                    existing_team_ids.add(group_id)

    logger.info(
        f"Existing team IDs: {existing_team_ids}, Current teams: {current_teams}"
    )

    # Compare team counts to detect changes
    teams_changed = len(current_teams) != len(existing_team_ids)
    if teams_changed:
        logger.info(
            f"Team count changed for repo {repo.id} (name: {repo.name}): {len(existing_team_ids)} -> {len(current_teams)}"
        )

    return teams_changed


def is_repo_visibility_changed(
    repo: Repository,
    github_client: Github,
    fetch_all_existing_docs_fn: FetchAllDocumentsFunction,
) -> bool:
    """
    Check if repository visibility has changed by comparing current visibility
    with inferred previous visibility from existing document permissions.

    Returns:
        True if visibility has changed
    """
    logger.info(
        f"Checking visibility change for repository {repo.id} (name: {repo.name})"
    )

    # Get current repository visibility
    current_repo_visibility = get_repository_visibility(repo)
    logger.info(f"Current repository visibility: {current_repo_visibility}")

    # Default to public visibility
    existing_repo_visibility: str = "public"

    # Check for collaborators group (indicates private repo)
    onyx_collaborators_group_id = build_ext_group_name_for_onyx(
        source=DocumentSource.GITHUB,
        ext_group_name=form_collaborators_group_id(repo.id),
    )
    existing_docs = fetch_all_existing_docs_fn(
        columns=[Document.id, Document.external_user_group_ids],
        limit=1,
        where_clause=Document.external_user_group_ids.contains(
            [onyx_collaborators_group_id]
        ),
    )

    if existing_docs:
        existing_repo_visibility = "private"
        logger.info(
            "Found documents with collaborators group, inferring private visibility"
        )
        visibility_changed = existing_repo_visibility != current_repo_visibility
        if visibility_changed:
            logger.info(
                f"Visibility changed for repo {repo.id} (name: {repo.name}): "
                f"{existing_repo_visibility} -> {current_repo_visibility}"
            )
        return visibility_changed

    # Check for organization group (indicates internal repo)
    org = repo.organization
    logger.info(f"Organization for repository {repo.id} (name: {repo.name}): {org}")
    if org:
        onyx_organization_group_id = build_ext_group_name_for_onyx(
            source=DocumentSource.GITHUB,
            ext_group_name=form_organization_group_id(org.id),
        )
        existing_docs = fetch_all_existing_docs_fn(
            columns=[Document.id, Document.external_user_group_ids],
            limit=1,
            where_clause=Document.external_user_group_ids.contains(
                [onyx_organization_group_id]
            ),
        )
        logger.info(f"Found {len(existing_docs)} existing docs with organization group")

        if existing_docs:
            existing_repo_visibility = "internal"
            logger.info(
                "Found documents with organization group, inferring internal visibility"
            )
            visibility_changed = existing_repo_visibility != current_repo_visibility
            if visibility_changed:
                logger.info(
                    f"Visibility changed for repo {repo.id} (name: {repo.name}): "
                    f"{existing_repo_visibility} -> {current_repo_visibility}"
                )
            return visibility_changed

    # No specific groups found, assume public visibility
    logger.info("No specific groups found, assuming public visibility")
    visibility_changed = existing_repo_visibility != current_repo_visibility
    if visibility_changed:
        logger.info(
            f"Visibility changed for repo {repo.id} (name: {repo.name}): "
            f"{existing_repo_visibility} -> {current_repo_visibility}"
        )
    return visibility_changed
