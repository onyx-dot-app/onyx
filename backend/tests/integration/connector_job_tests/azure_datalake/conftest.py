import logging
from collections.abc import Generator
from datetime import datetime, timezone

import pytest
from pydantic import BaseModel, ConfigDict

from onyx.configs.constants import DocumentSource
from onyx.connectors.azure_datalake.models import AzureDataLakeAuthMethod
from onyx.connectors.models import InputType
from onyx.db.enums import AccessType
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.connector import ConnectorManager
from tests.integration.common_utils.managers.credential import CredentialManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.reset import reset_all
from tests.integration.common_utils.test_models import DATestCCPair, DATestUser
from tests.utils.pytest_secrets import (
    pytest_collection_modifyitems as pytest_collection_modifyitems,
)
from tests.utils.pytest_secrets import pytest_configure as pytest_configure
from tests.utils.pytest_secrets import test_secrets as test_secrets
from tests.utils.secret_names import TestSecret

ACCOUNT = "onyxadlstest"
CONTAINER = "adls-perm-fixture"
# Not a member of the tenant, so no fixture path grants it access.
ADMIN_EMAIL = "admin@onyx.app"
OWNER_EMAIL = "test@danswerai.com"
RBAC_READER_EMAIL = "subash@onyx.app"
ACL_MEMBER_EMAIL = "raunak@onyx.app"
JOB_TIMEOUT_SECONDS = 15 * 60

logger = logging.getLogger(__name__)


class AzureDataLakePermissionEnvironment(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    admin_user: DATestUser
    owner_user: DATestUser
    rbac_reader_user: DATestUser
    acl_member_user: DATestUser
    cc_pair: DATestCCPair


def _certificate_credentials(values: dict[TestSecret, str]) -> dict[str, str]:
    return {
        "authentication_method": AzureDataLakeAuthMethod.CERTIFICATE.value,
        "adls_client_id": values[TestSecret.PERM_SYNC_SHAREPOINT_CLIENT_ID],
        "adls_directory_id": values[TestSecret.PERM_SYNC_SHAREPOINT_DIRECTORY_ID],
        "adls_private_key": values[TestSecret.PERM_SYNC_SHAREPOINT_PRIVATE_KEY],
        "adls_certificate_password": values[
            TestSecret.PERM_SYNC_SHAREPOINT_CERTIFICATE_PASSWORD
        ],
    }


@pytest.fixture(scope="module")
def azure_datalake_permission_environment(
    test_secrets: dict[TestSecret, str],
) -> Generator[AzureDataLakePermissionEnvironment, None, None]:
    try:
        reset_all()
        admin_user = UserManager.create(email=ADMIN_EMAIL)
        owner_user = UserManager.create(email=OWNER_EMAIL)
        rbac_reader_user = UserManager.create(email=RBAC_READER_EMAIL)
        acl_member_user = UserManager.create(email=ACL_MEMBER_EMAIL)

        credential = CredentialManager.create(
            source=DocumentSource.AZURE_DATALAKE,
            name="ADLS permission fixture",
            credential_json=_certificate_credentials(test_secrets),
            user_performing_action=admin_user,
        )
        connector = ConnectorManager.create(
            source=DocumentSource.AZURE_DATALAKE,
            name="ADLS permission fixture",
            input_type=InputType.POLL,
            connector_specific_config={
                "account_name": ACCOUNT,
                "container_name": CONTAINER,
            },
            access_type=AccessType.SYNC,
            user_performing_action=admin_user,
        )
        started_at = datetime.now(timezone.utc)
        cc_pair = CCPairManager.create(
            connector_id=connector.id,
            credential_id=credential.id,
            name="ADLS permission fixture",
            access_type=AccessType.SYNC,
            user_performing_action=admin_user,
        )
        CCPairManager.wait_for_indexing_completion(
            cc_pair=cc_pair,
            after=started_at,
            user_performing_action=admin_user,
            timeout=JOB_TIMEOUT_SECONDS,
        )
        CCPairManager.wait_for_sync(
            cc_pair=cc_pair,
            after=started_at,
            user_performing_action=admin_user,
            timeout=JOB_TIMEOUT_SECONDS,
        )
        # The group sync reads the exclusion groups from the synced access, so
        # a new one gets its members on the next run.
        resynced_at = datetime.now(timezone.utc)
        CCPairManager.sync(cc_pair=cc_pair, user_performing_action=admin_user)
        CCPairManager.wait_for_sync(
            cc_pair=cc_pair,
            after=resynced_at,
            user_performing_action=admin_user,
            timeout=JOB_TIMEOUT_SECONDS,
        )

        yield AzureDataLakePermissionEnvironment(
            admin_user=admin_user,
            owner_user=owner_user,
            rbac_reader_user=rbac_reader_user,
            acl_member_user=acl_member_user,
            cc_pair=cc_pair,
        )
    finally:
        try:
            reset_all()
        except Exception:
            logger.exception("Failed to reset integration test state")
            raise
