import os
from collections.abc import Generator
from datetime import datetime
from datetime import timezone

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.enums import AccessType
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.connector import ConnectorManager
from tests.integration.common_utils.managers.credential import CredentialManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.reset import reset_all
from tests.integration.common_utils.test_models import DATestCCPair
from tests.integration.common_utils.test_models import DATestConnector
from tests.integration.common_utils.test_models import DATestCredential
from tests.integration.common_utils.test_models import DATestUser


GitHubTestEnvSetupTuple = tuple[
    DATestUser,  # admin_user
    DATestUser,  # test_user_1
    DATestUser,  # test_user_2
    DATestCredential,  # github_credential
    DATestConnector,  # github_connector
    DATestCCPair,  # github_cc_pair
]


def _get_github_test_tokens() -> list[str]:
    """
    Returns a list of GitHub tokens to run the GitHub connector suite against.

    Minimal setup:
    - Set ONYX_GITHUB_PERMISSION_SYNC_TEST_ACCESS_TOKEN (token1)
    Optional:
    - Set ONYX_GITHUB_PERMISSION_SYNC_TEST_ACCESS_TOKEN_CLASSIC (token2 / classic)

    If the classic token is provided, the GitHub suite will run twice (once per token).
    """
    token_1 = os.environ.get("ONYX_GITHUB_PERMISSION_SYNC_TEST_ACCESS_TOKEN")
    # Prefer the new "classic" name, but keep backward compatibility.
    token_2 = os.environ.get("ONYX_GITHUB_PERMISSION_SYNC_TEST_ACCESS_TOKEN_CLASSIC")

    tokens: list[str] = []
    if token_1:
        tokens.append(token_1)
    if token_2:
        tokens.append(token_2)
    return tokens


@pytest.fixture(scope="module", params=_get_github_test_tokens())
def github_access_token(request: pytest.FixtureRequest) -> str:
    tokens = _get_github_test_tokens()
    if not tokens:
        pytest.skip(
            "Skipping GitHub tests due to missing env vars "
            "ONYX_GITHUB_PERMISSION_SYNC_TEST_ACCESS_TOKEN and "
            "ONYX_GITHUB_PERMISSION_SYNC_TEST_ACCESS_TOKEN_CLASSIC"
        )
    return request.param


@pytest.fixture(scope="module")
def github_test_env_setup(
    github_access_token: str,
) -> Generator[GitHubTestEnvSetupTuple]:
    """
    Create a complete GitHub test environment with:
    - 3 users with email IDs from environment variables
    - GitHub credentials using ACCESS_TOKEN_GITHUB from environment
    - GitHub connector configured for testing
    - Connector-Credential pair linking them together

    Returns:
        Tuple containing: (admin_user, test_user_1, test_user_2, github_credential, github_connector, github_cc_pair)
    """
    # Reset all resources before setting up the test environment
    reset_all()

    # Get user emails from environment (with fallbacks)
    admin_email = os.environ.get("ONYX_GITHUB_ADMIN_EMAIL", "admin@example.com")
    test_user_1_email = os.environ.get(
        "ONYX_GITHUB_TEST_USER_1_EMAIL", "subash@onyx.app"
    )
    test_user_2_email = os.environ.get(
        "ONYX_GITHUB_TEST_USER_2_EMAIL", "msubash203@gmail.com"
    )

    if not admin_email or not test_user_1_email or not test_user_2_email:
        pytest.skip(
            "Skipping GitHub test environment setup due to missing environment variables"
        )

    # Create users
    admin_user: DATestUser = UserManager.create(email=admin_email)
    test_user_1: DATestUser = UserManager.create(email=test_user_1_email)
    test_user_2: DATestUser = UserManager.create(email=test_user_2_email)

    # Create LLM provider - required for document search to work
    LLMProviderManager.create(user_performing_action=admin_user)

    # Create GitHub credentials
    github_credentials = {
        "github_access_token": github_access_token,
    }

    github_credential: DATestCredential = CredentialManager.create(
        source=DocumentSource.GITHUB,
        credential_json=github_credentials,
        user_performing_action=admin_user,
    )

    # Create GitHub connector
    github_connector: DATestConnector = ConnectorManager.create(
        name="GitHub Test Connector",
        input_type=InputType.POLL,
        source=DocumentSource.GITHUB,
        connector_specific_config={
            "repo_owner": "permission-sync-test",
            "include_prs": True,
            "repositories": "perm-sync-test-minimal",
            "include_issues": True,
        },
        access_type=AccessType.SYNC,
        user_performing_action=admin_user,
    )

    # Create CC pair linking connector and credential
    github_cc_pair: DATestCCPair = CCPairManager.create(
        credential_id=github_credential.id,
        connector_id=github_connector.id,
        name="GitHub Test CC Pair",
        access_type=AccessType.SYNC,
        user_performing_action=admin_user,
    )

    # Wait for initial indexing to complete
    # GitHub API operations can be slow due to rate limiting and network latency
    # Use a longer timeout for initial indexing to avoid flaky test failures
    before = datetime.now(tz=timezone.utc)
    CCPairManager.wait_for_indexing_completion(
        cc_pair=github_cc_pair,
        after=before,
        user_performing_action=admin_user,
        timeout=900,
    )

    yield admin_user, test_user_1, test_user_2, github_credential, github_connector, github_cc_pair
