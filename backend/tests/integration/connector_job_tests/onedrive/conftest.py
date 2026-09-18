import logging
from collections.abc import Generator
from datetime import datetime, timezone

import pytest
from pydantic import BaseModel, ConfigDict

from onyx.configs.constants import DocumentSource
from onyx.connectors.microsoft_utils.graph_auth import MicrosoftAuthMethod
from onyx.connectors.models import InputType
from onyx.db.enums import AccessType
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.connector import ConnectorManager
from tests.integration.common_utils.managers.credential import CredentialManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.reset import reset_all
from tests.integration.common_utils.test_models import DATestCCPair, DATestUser
from tests.utils.onedrive_fixture import (
    FIXTURE_EXCLUDED_PATHS,
    FixtureState,
    OneDriveFixtureProvisioner,
    build_integration_fixture_config,
    build_provisioner,
)
from tests.utils.pytest_secrets import (
    pytest_collection_modifyitems as pytest_collection_modifyitems,
)
from tests.utils.pytest_secrets import pytest_configure as pytest_configure
from tests.utils.pytest_secrets import test_secrets as test_secrets
from tests.utils.secret_names import TestSecret

ADMIN_EMAIL = "admin@onyx.app"
OUTSIDER_EMAIL = "onedrive-outsider@onyx.app"
JOB_TIMEOUT_SECONDS = 15 * 60

logger = logging.getLogger(__name__)


class OneDriveIntegrationEnvironment(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    provisioner: OneDriveFixtureProvisioner
    state: FixtureState
    admin_user: DATestUser
    owner_user: DATestUser
    primary_user: DATestUser
    second_owner_user: DATestUser
    alternate_user: DATestUser
    outsider_user: DATestUser
    onedrive_cc_pair: DATestCCPair
    sharepoint_cc_pair: DATestCCPair


def _onedrive_credentials(values: dict[TestSecret, str]) -> dict[str, str]:
    return {
        "authentication_method": MicrosoftAuthMethod.CERTIFICATE.value,
        "onedrive_client_id": values[TestSecret.PERM_SYNC_SHAREPOINT_CLIENT_ID],
        "onedrive_directory_id": values[TestSecret.PERM_SYNC_SHAREPOINT_DIRECTORY_ID],
        "onedrive_private_key": values[TestSecret.PERM_SYNC_SHAREPOINT_PRIVATE_KEY],
        "onedrive_certificate_password": values[
            TestSecret.PERM_SYNC_SHAREPOINT_CERTIFICATE_PASSWORD
        ],
    }


def _sharepoint_credentials(values: dict[TestSecret, str]) -> dict[str, str]:
    return {
        "authentication_method": MicrosoftAuthMethod.CERTIFICATE.value,
        "sp_client_id": values[TestSecret.PERM_SYNC_SHAREPOINT_CLIENT_ID],
        "sp_directory_id": values[TestSecret.PERM_SYNC_SHAREPOINT_DIRECTORY_ID],
        "sp_private_key": values[TestSecret.PERM_SYNC_SHAREPOINT_PRIVATE_KEY],
        "sp_certificate_password": values[
            TestSecret.PERM_SYNC_SHAREPOINT_CERTIFICATE_PASSWORD
        ],
    }


def _create_cc_pair(
    *,
    admin_user: DATestUser,
    source: DocumentSource,
    name: str,
    credential_json: dict[str, str],
    connector_specific_config: dict[str, object],
) -> DATestCCPair:
    credential = CredentialManager.create(
        source=source,
        name=name,
        credential_json=credential_json,
        user_performing_action=admin_user,
    )
    connector = ConnectorManager.create(
        source=source,
        name=name,
        input_type=InputType.POLL,
        connector_specific_config=connector_specific_config,
        access_type=AccessType.SYNC,
        user_performing_action=admin_user,
    )
    return CCPairManager.create(
        connector_id=connector.id,
        credential_id=credential.id,
        name=name,
        access_type=AccessType.SYNC,
        user_performing_action=admin_user,
    )


def _wait_for_initial_jobs(
    cc_pair: DATestCCPair,
    admin_user: DATestUser,
    started_at: datetime,
) -> None:
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


@pytest.fixture(scope="module")
def onedrive_integration_environment(
    test_secrets: dict[TestSecret, str],
) -> Generator[OneDriveIntegrationEnvironment, None, None]:
    provisioner = build_provisioner(build_integration_fixture_config())
    corpus_setup_started = False
    try:
        reset_all()
        corpus_setup_started = True
        state = provisioner.setup()

        admin_user = UserManager.create(email=ADMIN_EMAIL)
        owner_user = UserManager.create(email=state.owner.user_principal_name)
        primary_user = UserManager.create(email=state.primary_user.user_principal_name)
        alternate_user = UserManager.create(
            email=state.alternate_user.user_principal_name
        )
        existing_users = {
            user.email.lower(): user
            for user in (owner_user, primary_user, alternate_user)
        }
        second_owner_email = state.second_owner.user_principal_name.lower()
        second_owner_user = existing_users.get(second_owner_email)
        if second_owner_user is None:
            second_owner_user = UserManager.create(
                email=state.second_owner.user_principal_name
            )
        outsider_user = UserManager.create(email=OUTSIDER_EMAIL)
        LLMProviderManager.create(user_performing_action=admin_user)

        started_at = datetime.now(timezone.utc)
        onedrive_cc_pair = _create_cc_pair(
            admin_user=admin_user,
            source=DocumentSource.ONEDRIVE,
            name="OneDrive fixed corpus",
            credential_json=_onedrive_credentials(test_secrets),
            connector_specific_config={
                "users": [
                    state.owner.user_principal_name,
                    state.second_owner.user_principal_name,
                ],
                "all_users": False,
                "excluded_paths": FIXTURE_EXCLUDED_PATHS,
                "treat_organization_link_as_public": True,
            },
        )
        _wait_for_initial_jobs(onedrive_cc_pair, admin_user, started_at)

        sharepoint_started_at = datetime.now(timezone.utc)
        sharepoint_cc_pair = _create_cc_pair(
            admin_user=admin_user,
            source=DocumentSource.SHAREPOINT,
            name="OneDrive personal site overlap",
            credential_json=_sharepoint_credentials(test_secrets),
            connector_specific_config={
                "sites": [state.site.web_url],
                "include_site_pages": False,
                "include_site_documents": True,
                "excluded_paths": FIXTURE_EXCLUDED_PATHS,
                "treat_sharing_link_as_public": True,
            },
        )
        _wait_for_initial_jobs(sharepoint_cc_pair, admin_user, sharepoint_started_at)

        yield OneDriveIntegrationEnvironment(
            provisioner=provisioner,
            state=state,
            admin_user=admin_user,
            owner_user=owner_user,
            primary_user=primary_user,
            second_owner_user=second_owner_user,
            alternate_user=alternate_user,
            outsider_user=outsider_user,
            onedrive_cc_pair=onedrive_cc_pair,
            sharepoint_cc_pair=sharepoint_cc_pair,
        )
    finally:
        cleanup_errors: list[Exception] = []
        try:
            if corpus_setup_started:
                provisioner.setup()
        except Exception as error:
            logger.exception("Failed to restore the OneDrive integration corpus")
            cleanup_errors.append(error)
        finally:
            try:
                reset_all()
            except Exception as error:
                logger.exception("Failed to reset integration test state")
                cleanup_errors.append(error)
        if cleanup_errors:
            raise ExceptionGroup("OneDrive integration cleanup failed", cleanup_errors)
