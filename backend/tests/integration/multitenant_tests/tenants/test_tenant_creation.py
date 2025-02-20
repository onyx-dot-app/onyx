from onyx.configs.constants import DocumentSource
from onyx.db.enums import AccessType
from onyx.db.models import UserRole
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.connector import ConnectorManager
from tests.integration.common_utils.managers.credential import CredentialManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser


# Test flow from creating tenant to registering as a user
def test_tenant_creation(reset_multitenant: None) -> None:
    test_user: DATestUser = UserManager.create(name="test", email="test@test.com")

    assert UserManager.is_role(test_user, UserRole.ADMIN)

    test_credential = CredentialManager.create(
        name="admin_test_credential",
        source=DocumentSource.FILE,
        curator_public=False,
        user_performing_action=test_user,
    )

    test_connector = ConnectorManager.create(
        name="admin_test_connector",
        source=DocumentSource.FILE,
        access_type=AccessType.PRIVATE,
        user_performing_action=test_user,
    )

    test_cc_pair = CCPairManager.create(
        connector_id=test_connector.id,
        credential_id=test_credential.id,
        name="admin_test_cc_pair",
        access_type=AccessType.PRIVATE,
        user_performing_action=test_user,
    )

    CCPairManager.verify(cc_pair=test_cc_pair, user_performing_action=test_user)
