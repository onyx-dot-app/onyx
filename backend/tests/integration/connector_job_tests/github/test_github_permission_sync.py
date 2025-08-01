import os
from datetime import datetime
from datetime import timezone

import pytest
from github import Github

from onyx.utils.logger import setup_logger
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.document_search import (
    DocumentSearchManager,
)
from tests.integration.connector_job_tests.github.conftest import (
    GitHubTestEnvSetupTuple,
)
from tests.integration.connector_job_tests.github.utils import GitHubManager

logger = setup_logger()


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Permission tests are enterprise only",
)
def test_github_private_repo_permission_sync(
    github_test_env_setup: GitHubTestEnvSetupTuple,
) -> None:

    (
        admin_user,
        test_user_1,
        test_user_2,
        github_credential,
        github_connector,
        github_cc_pair,
    ) = github_test_env_setup

    # Create GitHub client from credential
    github_access_token = github_credential.credential_json["github_access_token"]
    github_client = Github(github_access_token)
    github_manager = GitHubManager(github_client)

    # Get repository configuration from connector
    repo_owner = github_connector.connector_specific_config["repo_owner"]
    repo_name = github_connector.connector_specific_config["repositories"]

    success = github_manager.change_repository_visibility(
        repo_owner=repo_owner, repo_name=repo_name, visibility="private"
    )

    if not success:
        pytest.fail(f"Failed to change repository {repo_owner}/{repo_name} to private")

    # Add test-team to repository at the start
    logger.info(f"Adding test-team to repository {repo_owner}/{repo_name}")
    team_added = github_manager.add_team_to_repository(
        repo_owner=repo_owner,
        repo_name=repo_name,
        team_slug="test-team",
        permission="pull",
    )

    if not team_added:
        logger.warning(
            f"Failed to add test-team to repository {repo_owner}/{repo_name}"
        )

    try:
        CCPairManager.sync(
            cc_pair=github_cc_pair,
            user_performing_action=admin_user,
        )

        # Use a longer timeout for GitHub permission sync operations
        # GitHub API operations can be slow, especially with rate limiting
        # This accounts for document sync, group sync, and vespa sync operations
        CCPairManager.wait_for_sync(
            cc_pair=github_cc_pair,
            user_performing_action=admin_user,
            after=datetime.now(timezone.utc),
            should_wait_for_group_sync=True,
            timeout=float("inf"),
        )

        test_user_1_results = DocumentSearchManager.search_documents(
            query="Is there any PR about middlewares?",
            user_performing_action=test_user_1,
        )

        test_user_2_results = DocumentSearchManager.search_documents(
            query="Is there any PR about middlewares?",
            user_performing_action=test_user_2,
        )

        logger.info(f"test_user_1_results: {test_user_1_results}")
        logger.info(f"test_user_2_results: {test_user_2_results}")

        assert len(test_user_1_results) > 0
        assert len(test_user_2_results) == 0

    finally:
        # Remove test-team from repository at the end
        logger.info(f"Removing test-team from repository {repo_owner}/{repo_name}")
        team_removed = github_manager.remove_team_from_repository(
            repo_owner=repo_owner, repo_name=repo_name, team_slug="test-team"
        )

        if not team_removed:
            logger.warning(
                f"Failed to remove test-team from repository {repo_owner}/{repo_name}"
            )


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Permission tests are enterprise only",
)
def test_github_public_repo_permission_sync(
    github_test_env_setup: GitHubTestEnvSetupTuple,
) -> None:
    """
    Test that when a repository is changed to public, both users can access the documents.
    """
    (
        admin_user,
        test_user_1,
        test_user_2,
        github_credential,
        github_connector,
        github_cc_pair,
    ) = github_test_env_setup

    # Create GitHub client from credential
    github_access_token = github_credential.credential_json["github_access_token"]
    github_client = Github(github_access_token)
    github_manager = GitHubManager(github_client)

    # Get repository configuration from connector
    repo_owner = github_connector.connector_specific_config["repo_owner"]
    repo_name = github_connector.connector_specific_config["repositories"]

    # Change repository to public
    logger.info(f"Changing repository {repo_owner}/{repo_name} to public")
    success = github_manager.change_repository_visibility(
        repo_owner=repo_owner, repo_name=repo_name, visibility="public"
    )

    if not success:
        pytest.fail(f"Failed to change repository {repo_owner}/{repo_name} to public")

    # Verify repository is now public
    current_visibility = github_manager.get_repository_visibility(
        repo_owner=repo_owner, repo_name=repo_name
    )
    logger.info(f"Repository {repo_owner}/{repo_name} visibility: {current_visibility}")
    assert (
        current_visibility == "public"
    ), f"Repository should be public, but is {current_visibility}"

    # Trigger sync to update permissions
    CCPairManager.sync(
        cc_pair=github_cc_pair,
        user_performing_action=admin_user,
    )

    # Wait for sync to complete with group sync
    # Public repositories should be accessible to all users
    CCPairManager.wait_for_sync(
        cc_pair=github_cc_pair,
        user_performing_action=admin_user,
        after=datetime.now(timezone.utc),
        should_wait_for_group_sync=True,
        timeout=float("inf"),
    )

    # Test document search for both users
    test_user_1_results = DocumentSearchManager.search_documents(
        query="How many PR's are there?",
        user_performing_action=test_user_1,
    )

    test_user_2_results = DocumentSearchManager.search_documents(
        query="How many PR's are there?",
        user_performing_action=test_user_2,
    )

    logger.info(f"test_user_1_results: {test_user_1_results}")
    logger.info(f"test_user_2_results: {test_user_2_results}")

    # Both users should have access to the public repository documents
    assert (
        len(test_user_1_results) > 0
    ), "test_user_1 should have access to public repository documents"
    assert (
        len(test_user_2_results) > 0
    ), "test_user_2 should have access to public repository documents"

    # Verify that both users get the same results (since repo is public)
    assert len(test_user_1_results) == len(
        test_user_2_results
    ), "Both users should see the same documents from public repository"


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Permission tests are enterprise only",
)
def test_github_internal_repo_permission_sync(
    github_test_env_setup: GitHubTestEnvSetupTuple,
) -> None:
    """
    Test that when a repository is changed to internal, test_user_1 has access but test_user_2 doesn't.
    Internal repositories are accessible only to organization members.
    """
    (
        admin_user,
        test_user_1,
        test_user_2,
        github_credential,
        github_connector,
        github_cc_pair,
    ) = github_test_env_setup

    # Create GitHub client from credential
    github_access_token = github_credential.credential_json["github_access_token"]
    github_client = Github(github_access_token)
    github_manager = GitHubManager(github_client)

    # Get repository configuration from connector
    repo_owner = github_connector.connector_specific_config["repo_owner"]
    repo_name = github_connector.connector_specific_config["repositories"]

    # Change repository to internal
    logger.info(f"Changing repository {repo_owner}/{repo_name} to internal")
    success = github_manager.change_repository_visibility(
        repo_owner=repo_owner, repo_name=repo_name, visibility="internal"
    )

    if not success:
        pytest.fail(f"Failed to change repository {repo_owner}/{repo_name} to internal")

    # Verify repository is now internal
    current_visibility = github_manager.get_repository_visibility(
        repo_owner=repo_owner, repo_name=repo_name
    )
    logger.info(f"Repository {repo_owner}/{repo_name} visibility: {current_visibility}")
    assert (
        current_visibility == "internal"
    ), f"Repository should be internal, but is {current_visibility}"

    # Trigger sync to update permissions
    CCPairManager.sync(
        cc_pair=github_cc_pair,
        user_performing_action=admin_user,
    )

    # Wait for sync to complete with group sync
    # Internal repositories should be accessible only to organization members
    CCPairManager.wait_for_sync(
        cc_pair=github_cc_pair,
        user_performing_action=admin_user,
        after=datetime.now(timezone.utc),
        should_wait_for_group_sync=True,
        timeout=float("inf"),
    )

    # Test document search for both users
    test_user_1_results = DocumentSearchManager.search_documents(
        query="How many PR's are there?",
        user_performing_action=test_user_1,
    )

    test_user_2_results = DocumentSearchManager.search_documents(
        query="How many PR's are there?",
        user_performing_action=test_user_2,
    )

    logger.info(f"test_user_1_results: {test_user_1_results}")
    logger.info(f"test_user_2_results: {test_user_2_results}")

    # For internal repositories:
    # - test_user_1 should have access (assuming they're part of the organization)
    # - test_user_2 should NOT have access (assuming they're not part of the organization)
    assert (
        len(test_user_1_results) > 0
    ), "test_user_1 should have access to internal repository documents (organization member)"
    assert (
        len(test_user_2_results) == 0
    ), "test_user_2 should NOT have access to internal repository documents (not organization member)"
