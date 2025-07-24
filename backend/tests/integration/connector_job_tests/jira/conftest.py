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
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestCCPair
from tests.integration.common_utils.test_models import DATestConnector
from tests.integration.common_utils.test_models import DATestCredential
from tests.integration.common_utils.test_models import DATestUser


JiraTestEnvSetupTuple = tuple[
    DATestUser,
    DATestCredential,
    DATestConnector,
    DATestCCPair,
]


@pytest.fixture()
def jira_test_env_setup() -> Generator[JiraTestEnvSetupTuple]:
    jira_base_url = os.environ["JIRA_BASE_URL"]
    jira_user_email = os.environ["JIRA_USER_EMAIL"]
    jira_api_token = os.environ["JIRA_API_TOKEN"]

    credentials = {
        "jira_user_email": jira_user_email,
        "jira_api_token": jira_api_token,
    }

    admin_user: DATestUser = UserManager.create(email=jira_user_email)
    credential: DATestCredential = CredentialManager.create(
        source=DocumentSource.JIRA,
        credential_json=credentials,
        user_performing_action=admin_user,
    )
    connector: DATestConnector = ConnectorManager.create(
        name="Jira Test",
        input_type=InputType.POLL,
        source=DocumentSource.JIRA,
        connector_specific_config={
            "jira_base_url": jira_base_url,
        },
        access_type=AccessType.SYNC,
        user_performing_action=admin_user,
    )
    cc_pair: DATestCCPair = CCPairManager.create(
        credential_id=credential.id,
        connector_id=connector.id,
        access_type=AccessType.SYNC,
        user_performing_action=admin_user,
    )
    before = datetime.now(tz=timezone.utc)
    CCPairManager.wait_for_indexing_completion(
        cc_pair=cc_pair, after=before, user_performing_action=admin_user
    )

    yield admin_user, credential, connector, cc_pair
