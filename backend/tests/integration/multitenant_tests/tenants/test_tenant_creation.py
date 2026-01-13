from http import HTTPStatus
from uuid import uuid4

import requests

from onyx.configs.constants import DocumentSource
from onyx.db.enums import AccessType
from onyx.db.models import UserRole
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.connector import ConnectorManager
from tests.integration.common_utils.managers.credential import CredentialManager
from tests.integration.common_utils.managers.image_generation import (
    ImageGenerationConfigManager,
)
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser


def test_first_user_is_admin(reset_multitenant: None) -> None:
    """Test that the first user of a tenant is automatically assigned ADMIN role."""
    unique = uuid4().hex
    test_user: DATestUser = UserManager.create(
        name=f"test_{unique}", email=f"test_{unique}@example.com"
    )
    assert UserManager.is_role(test_user, UserRole.ADMIN)


def test_admin_can_create_credential(reset_multitenant: None) -> None:
    """Test that an admin user can create a credential in their tenant."""
    # Create admin user
    unique = uuid4().hex
    test_user: DATestUser = UserManager.create(
        name=f"test_{unique}", email=f"test_{unique}@example.com"
    )
    assert UserManager.is_role(test_user, UserRole.ADMIN)

    # Create credential
    test_credential = CredentialManager.create(
        name="admin_test_credential",
        source=DocumentSource.FILE,
        curator_public=False,
        user_performing_action=test_user,
    )
    assert test_credential is not None


def test_admin_can_create_connector(reset_multitenant: None) -> None:
    """Test that an admin user can create a connector in their tenant."""
    # Create admin user
    unique = uuid4().hex
    test_user: DATestUser = UserManager.create(
        name=f"test_{unique}", email=f"test_{unique}@example.com"
    )
    assert UserManager.is_role(test_user, UserRole.ADMIN)

    # Create connector
    test_connector = ConnectorManager.create(
        name="admin_test_connector",
        source=DocumentSource.FILE,
        access_type=AccessType.PRIVATE,
        user_performing_action=test_user,
    )
    assert test_connector is not None


def test_admin_can_create_and_verify_cc_pair(reset_multitenant: None) -> None:
    """Test that an admin user can create and verify a connector-credential pair in their tenant."""
    # Create admin user
    unique = uuid4().hex
    test_user: DATestUser = UserManager.create(
        name=f"test_{unique}", email=f"test_{unique}@example.com"
    )
    assert UserManager.is_role(test_user, UserRole.ADMIN)

    # Create credential
    test_credential = CredentialManager.create(
        name="admin_test_credential",
        source=DocumentSource.FILE,
        curator_public=False,
        user_performing_action=test_user,
    )

    # Create connector
    test_connector = ConnectorManager.create(
        name="admin_test_connector",
        source=DocumentSource.FILE,
        access_type=AccessType.PRIVATE,
        user_performing_action=test_user,
    )

    # Create cc_pair
    test_cc_pair = CCPairManager.create(
        connector_id=test_connector.id,
        credential_id=test_credential.id,
        name="admin_test_cc_pair",
        access_type=AccessType.PRIVATE,
        user_performing_action=test_user,
    )
    assert test_cc_pair is not None

    # Verify cc_pair
    CCPairManager.verify(cc_pair=test_cc_pair, user_performing_action=test_user)


def test_settings_access() -> None:
    """Calls to the enterprise settings endpoint without authentication should fail with
    403 (and not 500, which will lock the web UI into a "maintenance mode" page)"""

    response = requests.get(url=f"{API_SERVER_URL}/enterprise-settings")
    assert response.status_code == HTTPStatus.FORBIDDEN


def test_image_gen_config_created_on_tenant_provision(reset_multitenant: None) -> None:
    """Test that image generation config is automatically created when a tenant is provisioned."""
    unique = uuid4().hex
    test_user: DATestUser = UserManager.create(
        name=f"test_{unique}", email=f"test_{unique}@example.com"
    )
    assert UserManager.is_role(test_user, UserRole.ADMIN)

    # Check if image gen config was created during tenant provisioning
    all_configs = ImageGenerationConfigManager.get_all(user_performing_action=test_user)

    # Should have at least one config created during provisioning
    assert (
        len(all_configs) > 0
    ), "Image generation config should be created during tenant provisioning"

    # Verify a default config exists
    default_configs = [c for c in all_configs if c.is_default]
    assert (
        len(default_configs) == 1
    ), "Exactly one default image generation config should exist"

    # Verify expected properties
    default_config = default_configs[0]
    assert default_config.image_provider_id == "openai_gpt_image_1"
    assert default_config.model_name == "gpt-image-1"
