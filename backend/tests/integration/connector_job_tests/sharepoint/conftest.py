import os
from collections.abc import Generator
from datetime import datetime
from datetime import timezone

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.connectors.sharepoint.connector import SharepointAuthMethod
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

SharepointTestEnvSetupTuple = tuple[
    DATestUser,  # admin_user
    DATestUser,  # regular_user_1
    DATestUser,  # regular_user_2
    DATestCredential,
    DATestConnector,
    DATestCCPair,
]


@pytest.fixture(scope="module")
def sharepoint_test_env_setup() -> Generator[SharepointTestEnvSetupTuple]:
    # Reset all data before running the test
    reset_all()
    # Required environment variables for SharePoint certificate authentication
    sp_client_id = os.environ.get("PERM_SYNC_SHAREPOINT_CLIENT_ID")
    sp_private_key = os.environ.get("PERM_SYNC_SHAREPOINT_PRIVATE_KEY")
    sp_certificate_password = os.environ.get(
        "PERM_SYNC_SHAREPOINT_CERTIFICATE_PASSWORD"
    )
    sp_directory_id = os.environ.get("PERM_SYNC_SHAREPOINT_DIRECTORY_ID")
    sharepoint_sites = "https://danswerai.sharepoint.com/sites/Permisisonsync"
    admin_email = "admin@onyx.app"
    user1_email = "subash@onyx.app"
    user2_email = "raunak@onyx.app"

    if not sp_private_key or not sp_certificate_password or not sp_directory_id:
        pytest.skip("Skipping test because required environment variables are not set")

    # Certificate-based credentials
    credentials = {
        "authentication_method": SharepointAuthMethod.CERTIFICATE.value,
        "sp_client_id": sp_client_id,
        "sp_private_key": sp_private_key,
        "sp_certificate_password": sp_certificate_password,
        "sp_directory_id": sp_directory_id,
    }

    # Create users
    admin_user: DATestUser = UserManager.create(email=admin_email)
    regular_user_1: DATestUser = UserManager.create(email=user1_email)
    regular_user_2: DATestUser = UserManager.create(email=user2_email)

    # Create LLM provider for search functionality
    LLMProviderManager.create(user_performing_action=admin_user)

    # Create credential
    credential: DATestCredential = CredentialManager.create(
        source=DocumentSource.SHAREPOINT,
        credential_json=credentials,
        user_performing_action=admin_user,
    )

    # Create connector with SharePoint-specific configuration
    connector: DATestConnector = ConnectorManager.create(
        name="SharePoint Test",
        input_type=InputType.POLL,
        source=DocumentSource.SHAREPOINT,
        connector_specific_config={
            "sites": sharepoint_sites.split(","),
        },
        access_type=AccessType.SYNC,  # Enable permission sync
        user_performing_action=admin_user,
    )

    # Create CC pair with permission sync enabled
    cc_pair: DATestCCPair = CCPairManager.create(
        credential_id=credential.id,
        connector_id=connector.id,
        access_type=AccessType.SYNC,  # Enable permission sync
        user_performing_action=admin_user,
    )

    # Wait for both indexing and permission sync to complete
    before = datetime.now(tz=timezone.utc)
    CCPairManager.wait_for_indexing_completion(
        cc_pair=cc_pair,
        after=before,
        user_performing_action=admin_user,
        timeout=float("inf"),
    )

    # Wait for permission sync completion specifically
    CCPairManager.wait_for_sync(
        cc_pair=cc_pair,
        after=before,
        user_performing_action=admin_user,
        timeout=float("inf"),
    )

    yield admin_user, regular_user_1, regular_user_2, credential, connector, cc_pair
