import json
import os
from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from uuid import uuid4

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.google_utils.resources import GoogleDriveService
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY,
)
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_PRIMARY_ADMIN_KEY,
)
from onyx.connectors.models import InputType
from onyx.db.enums import AccessType
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.connector import ConnectorManager
from tests.integration.common_utils.managers.credential import CredentialManager
from tests.integration.common_utils.managers.document_search import (
    DocumentSearchManager,
)
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestCCPair
from tests.integration.common_utils.test_models import DATestConnector
from tests.integration.common_utils.test_models import DATestCredential
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.common_utils.vespa import vespa_fixture
from tests.integration.connector_job_tests.google.google_drive_api_utils import (
    GoogleDriveManager,
)


@pytest.fixture()
def google_drive_test_env_setup() -> Generator[
    tuple[GoogleDriveService, str, DATestCCPair, DATestUser, DATestUser, DATestUser],
    None,
    None,
]:
    # Creating an admin user (first user created is automatically an admin)
    admin_user: DATestUser = UserManager.create(email="admin@onyx-test.com")
    # Creating a non-admin user
    test_user_1: DATestUser = UserManager.create(email="test_user_1@onyx-test.com")
    # Creating a non-admin user
    test_user_2: DATestUser = UserManager.create(email="test_user_2@onyx-test.com")

    service_account_key = os.environ["FULL_CONTROL_DRIVE_SERVICE_ACCOUNT"]
    drive_id: str | None = None
    drive_service: GoogleDriveService | None = None

    try:
        credentials = {
            DB_CREDENTIALS_PRIMARY_ADMIN_KEY: admin_user.email,
            DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY: service_account_key,
        }

        # Setup Google Drive
        drive_service = GoogleDriveManager.create_impersonated_drive_service(
            json.loads(service_account_key), admin_user.email
        )
        test_id = str(uuid4())
        drive_id = GoogleDriveManager.create_shared_drive(
            drive_service, admin_user.email, test_id
        )

        # Setup Onyx infrastructure
        LLMProviderManager.create(user_performing_action=admin_user)

        before = datetime.now(timezone.utc)
        credential: DATestCredential = CredentialManager.create(
            source=DocumentSource.GOOGLE_DRIVE,
            credential_json=credentials,
            user_performing_action=admin_user,
        )
        connector: DATestConnector = ConnectorManager.create(
            name="Google Drive Test",
            input_type=InputType.POLL,
            source=DocumentSource.GOOGLE_DRIVE,
            connector_specific_config={
                "shared_drive_urls": f"https://drive.google.com/drive/folders/{drive_id}"
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
        CCPairManager.wait_for_indexing_completion(
            cc_pair=cc_pair, after=before, user_performing_action=admin_user
        )

        yield drive_service, drive_id, cc_pair, admin_user, test_user_1, test_user_2

    except json.JSONDecodeError:
        pytest.skip("FULL_CONTROL_DRIVE_SERVICE_ACCOUNT is not valid JSON")
    finally:
        # Cleanup drive and file
        if drive_id is not None:
            GoogleDriveManager.cleanup_drive(drive_service, drive_id)


@pytest.mark.xfail(reason="Needs to be tested for flakiness")
def test_google_permission_sync(
    reset: None,
    vespa_client: vespa_fixture,
    google_drive_test_env_setup: tuple[
        GoogleDriveService, str, DATestCCPair, DATestUser, DATestUser, DATestUser
    ],
) -> None:
    (
        drive_service,
        drive_id,
        cc_pair,
        admin_user,
        test_user_1,
        test_user_2,
    ) = google_drive_test_env_setup

    # ----------------------BASELINE TEST----------------------
    before = datetime.now(timezone.utc)

    # Create empty test doc in drive
    doc_id_1 = GoogleDriveManager.create_empty_doc(drive_service, drive_id)

    # Append text to doc
    doc_text_1 = "The secret number is 12345"
    GoogleDriveManager.append_text_to_doc(drive_service, doc_id_1, doc_text_1)

    # run indexing
    CCPairManager.run_once(
        cc_pair, from_beginning=True, user_performing_action=admin_user
    )
    CCPairManager.wait_for_indexing_completion(
        cc_pair=cc_pair, after=before, user_performing_action=admin_user
    )

    # run permission sync
    CCPairManager.sync(
        cc_pair=cc_pair,
        user_performing_action=admin_user,
    )
    CCPairManager.wait_for_sync(
        cc_pair=cc_pair,
        after=before,
        number_of_updated_docs=1,
        user_performing_action=admin_user,
    )

    # Verify admin has access to document
    admin_results = DocumentSearchManager.search_documents(
        query="secret number", user_performing_action=admin_user
    )
    assert doc_text_1 in [result.strip("\ufeff") for result in admin_results]

    # Verify test_user_1 cannot access document
    user1_results = DocumentSearchManager.search_documents(
        query="secret number", user_performing_action=test_user_1
    )
    assert doc_text_1 not in [result.strip("\ufeff") for result in user1_results]

    # ----------------------GRANT USER 1 DOC PERMISSIONS TEST--------------------------
    before = datetime.now(timezone.utc)

    # Grant user 1 access to document 1
    GoogleDriveManager.update_file_permissions(
        drive_service=drive_service,
        file_id=doc_id_1,
        email=test_user_1.email,
        role="reader",
    )

    # Create a second doc in the drive which user 1 should not have access to
    doc_id_2 = GoogleDriveManager.create_empty_doc(drive_service, drive_id)
    doc_text_2 = "The secret number is 67890"
    GoogleDriveManager.append_text_to_doc(drive_service, doc_id_2, doc_text_2)

    # Run indexing
    CCPairManager.run_once(
        cc_pair, from_beginning=True, user_performing_action=admin_user
    )
    CCPairManager.wait_for_indexing_completion(
        cc_pair=cc_pair,
        after=before,
        user_performing_action=admin_user,
    )

    # Run permission sync
    CCPairManager.sync(
        cc_pair=cc_pair,
        user_performing_action=admin_user,
    )
    CCPairManager.wait_for_sync(
        cc_pair=cc_pair,
        after=before,
        number_of_updated_docs=1,
        user_performing_action=admin_user,
    )

    # Verify admin can access both documents
    admin_results = DocumentSearchManager.search_documents(
        query="secret number", user_performing_action=admin_user
    )
    assert {doc_text_1, doc_text_2} == {
        result.strip("\ufeff") for result in admin_results
    }

    # Verify user 1 can access document 1
    user1_results = DocumentSearchManager.search_documents(
        query="secret number", user_performing_action=test_user_1
    )
    assert doc_text_1 in [result.strip("\ufeff") for result in user1_results]

    # Verify user 1 cannot access document 2
    user1_results_2 = DocumentSearchManager.search_documents(
        query="secret number", user_performing_action=test_user_1
    )
    assert doc_text_2 not in [result.strip("\ufeff") for result in user1_results_2]

    # ----------------------REMOVE USER 1 DOC PERMISSIONS TEST--------------------------
    before = datetime.now(timezone.utc)

    # Remove user 1 access to document 1
    GoogleDriveManager.remove_file_permissions(
        drive_service=drive_service, file_id=doc_id_1, email=test_user_1.email
    )
    # Run permission sync
    CCPairManager.sync(
        cc_pair=cc_pair,
        user_performing_action=admin_user,
    )
    CCPairManager.wait_for_sync(
        cc_pair=cc_pair,
        after=before,
        number_of_updated_docs=1,
        user_performing_action=admin_user,
    )

    # Verify admin can access both documents
    admin_results = DocumentSearchManager.search_documents(
        query="secret number", user_performing_action=admin_user
    )
    assert {doc_text_1, doc_text_2} == {
        result.strip("\ufeff") for result in admin_results
    }

    # Verify user 1 cannot access either document
    user1_results = DocumentSearchManager.search_documents(
        query="secret numbers", user_performing_action=test_user_1
    )
    assert {result.strip("\ufeff") for result in user1_results} == set()

    # ----------------------GRANT USER 1 DRIVE PERMISSIONS TEST--------------------------
    before = datetime.now(timezone.utc)

    # Grant user 1 access to drive
    GoogleDriveManager.update_file_permissions(
        drive_service=drive_service,
        file_id=drive_id,
        email=test_user_1.email,
        role="reader",
    )

    # Run permission sync
    CCPairManager.sync(
        cc_pair=cc_pair,
        user_performing_action=admin_user,
    )

    CCPairManager.wait_for_sync(
        cc_pair=cc_pair,
        after=before,
        number_of_updated_docs=2,
        user_performing_action=admin_user,
        # if we are only updating the group definition for this test we use this varaiable,
        # since it doesn't result in a vespa sync so we don't want to wait for it
        should_wait_for_vespa_sync=False,
    )

    # Verify user 1 can access both documents
    user1_results = DocumentSearchManager.search_documents(
        query="secret numbers", user_performing_action=test_user_1
    )
    assert {doc_text_1, doc_text_2} == {
        result.strip("\ufeff") for result in user1_results
    }

    # ----------------------MAKE DRIVE PUBLIC TEST--------------------------
    before = datetime.now(timezone.utc)

    # Unable to make drive itself public as Google's security policies prevent this, so we make the documents public instead
    GoogleDriveManager.make_file_public(drive_service, doc_id_1)
    GoogleDriveManager.make_file_public(drive_service, doc_id_2)

    # Run permission sync
    CCPairManager.sync(
        cc_pair=cc_pair,
        user_performing_action=admin_user,
    )
    CCPairManager.wait_for_sync(
        cc_pair=cc_pair,
        after=before,
        number_of_updated_docs=2,
        user_performing_action=admin_user,
    )

    # Verify all users can access both documents
    admin_results = DocumentSearchManager.search_documents(
        query="secret number", user_performing_action=admin_user
    )
    assert {doc_text_1, doc_text_2} == {
        result.strip("\ufeff") for result in admin_results
    }

    user1_results = DocumentSearchManager.search_documents(
        query="secret number", user_performing_action=test_user_1
    )
    assert {doc_text_1, doc_text_2} == {
        result.strip("\ufeff") for result in user1_results
    }

    user2_results = DocumentSearchManager.search_documents(
        query="secret number", user_performing_action=test_user_2
    )
    assert {doc_text_1, doc_text_2} == {
        result.strip("\ufeff") for result in user2_results
    }
