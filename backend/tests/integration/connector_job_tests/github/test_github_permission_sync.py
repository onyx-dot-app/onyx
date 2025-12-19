import os
from datetime import datetime
from datetime import timezone

import pytest
from github import Github

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.utils.logger import setup_logger
from tests.integration.common_utils.document_acl import (
    get_all_connector_documents,
)
from tests.integration.common_utils.document_acl import (
    get_user_document_access_via_acl,
)
from tests.integration.common_utils.managers.cc_pair import CCPairManager
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
        after = datetime.now(timezone.utc)
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
            after=after,
            should_wait_for_group_sync=True,
            timeout=float("inf"),
        )

        # ACL-based verification
        with get_session_with_current_tenant() as db_session:
            # Get all documents for this connector
            all_document_ids = get_all_connector_documents(github_cc_pair, db_session)

            # Test access for both users using ACL verification
            accessible_docs_user1 = get_user_document_access_via_acl(
                test_user=test_user_1,
                document_ids=all_document_ids,
                db_session=db_session,
            )

            accessible_docs_user2 = get_user_document_access_via_acl(
                test_user=test_user_2,
                document_ids=all_document_ids,
                db_session=db_session,
            )

            logger.info(
                f"test_user_1 has access to {len(accessible_docs_user1)} documents"
            )
            logger.info(
                f"test_user_2 has access to {len(accessible_docs_user2)} documents"
            )

            # test_user_1 (part of test-team) should have access
            # test_user_2 (not part of test-team) should NOT have access
            assert len(accessible_docs_user1) > 0, (
                f"test_user_1 should have access to private repository documents. "
                f"Found {len(accessible_docs_user1)} accessible docs out of "
                f"{len(all_document_ids)} total"
            )
            assert len(accessible_docs_user2) == 0, (
                f"test_user_2 should NOT have access to private repository documents. "
                f"Found {len(accessible_docs_user2)} accessible docs out of "
                f"{len(all_document_ids)} total"
            )

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
    after = datetime.now(timezone.utc)
    CCPairManager.sync(
        cc_pair=github_cc_pair,
        user_performing_action=admin_user,
    )

    # Wait for sync to complete with group sync
    # Public repositories should be accessible to all users
    CCPairManager.wait_for_sync(
        cc_pair=github_cc_pair,
        user_performing_action=admin_user,
        after=after,
        should_wait_for_group_sync=True,
        timeout=float("inf"),
    )

    # ACL-based verification
    with get_session_with_current_tenant() as db_session:
        # Get all documents for this connector
        all_document_ids = get_all_connector_documents(github_cc_pair, db_session)

        # Test access for both users using ACL verification
        accessible_docs_user1 = get_user_document_access_via_acl(
            test_user=test_user_1,
            document_ids=all_document_ids,
            db_session=db_session,
        )

        accessible_docs_user2 = get_user_document_access_via_acl(
            test_user=test_user_2,
            document_ids=all_document_ids,
            db_session=db_session,
        )

        logger.info(f"test_user_1 has access to {len(accessible_docs_user1)} documents")
        logger.info(f"test_user_2 has access to {len(accessible_docs_user2)} documents")

        # Both users should have access to the public repository documents
        assert len(accessible_docs_user1) > 0, (
            f"test_user_1 should have access to public repository documents. "
            f"Found {len(accessible_docs_user1)} accessible docs out of "
            f"{len(all_document_ids)} total"
        )
        assert len(accessible_docs_user2) > 0, (
            f"test_user_2 should have access to public repository documents. "
            f"Found {len(accessible_docs_user2)} accessible docs out of "
            f"{len(all_document_ids)} total"
        )

        # Verify that both users get the same results (since repo is public)
        assert len(accessible_docs_user1) == len(accessible_docs_user2), (
            f"Both users should see the same documents from public repository. "
            f"User1: {len(accessible_docs_user1)}, User2: {len(accessible_docs_user2)}"
        )


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
    after = datetime.now(timezone.utc)
    CCPairManager.sync(
        cc_pair=github_cc_pair,
        user_performing_action=admin_user,
    )

    # Wait for sync to complete with group sync
    # Internal repositories should be accessible only to organization members
    CCPairManager.wait_for_sync(
        cc_pair=github_cc_pair,
        user_performing_action=admin_user,
        after=after,
        should_wait_for_group_sync=True,
        timeout=float("inf"),
    )

    #  ACL-based verification
    with get_session_with_current_tenant() as db_session:
        # Get all documents for this connector
        all_document_ids = get_all_connector_documents(github_cc_pair, db_session)

        # Test access for both users using ACL verification
        accessible_docs_user1 = get_user_document_access_via_acl(
            test_user=test_user_1,
            document_ids=all_document_ids,
            db_session=db_session,
        )

        accessible_docs_user2 = get_user_document_access_via_acl(
            test_user=test_user_2,
            document_ids=all_document_ids,
            db_session=db_session,
        )

        logger.info(f"test_user_1 has access to {len(accessible_docs_user1)} documents")
        logger.info(f"test_user_2 has access to {len(accessible_docs_user2)} documents")

        # For internal repositories:
        # - test_user_1 should have access (assuming they're part of the organization)
        # - test_user_2 should NOT have access (assuming they're not part of the organization)
        assert len(accessible_docs_user1) > 0, (
            f"test_user_1 should have access to internal repository documents (organization member). "
            f"Found {len(accessible_docs_user1)} accessible docs out of "
            f"{len(all_document_ids)} total"
        )
        assert len(accessible_docs_user2) == 0, (
            f"test_user_2 should NOT have access to internal repository documents (not organization member). "
            f"Found {len(accessible_docs_user2)} accessible docs out of "
            f"{len(all_document_ids)} total"
        )
