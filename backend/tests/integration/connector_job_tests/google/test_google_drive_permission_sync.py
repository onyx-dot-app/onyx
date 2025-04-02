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
def google_drive_test_env_setup() -> (
    Generator[
        tuple[
            GoogleDriveService, str, DATestCCPair, DATestUser, DATestUser, DATestUser
        ],
        None,
        None,
    ]
):
    print("Starting google_drive_test_env_setup fixture")
    # Creating an admin user (first user created is automatically an admin)
    admin_user: DATestUser = UserManager.create(email="admin@onyx-test.com")
    print(f"Created admin user: {admin_user.email}, id: {admin_user.id}")
    # Creating a non-admin user
    test_user_1: DATestUser = UserManager.create(email="test_user_1@onyx-test.com")
    print(f"Created test user 1: {test_user_1.email}, id: {test_user_1.id}")
    # Creating a non-admin user
    test_user_2: DATestUser = UserManager.create(email="test_user_2@onyx-test.com")
    print(f"Created test user 2: {test_user_2.email}, id: {test_user_2.id}")

    service_account_key = os.environ["FULL_CONTROL_DRIVE_SERVICE_ACCOUNT"]
    print("Retrieved service account key from environment")
    drive_id: str | None = None
    drive_service: GoogleDriveService | None = None

    try:
        print("Setting up credentials dictionary")
        credentials = {
            DB_CREDENTIALS_PRIMARY_ADMIN_KEY: admin_user.email,
            DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY: service_account_key,
        }

        # Setup Google Drive
        print("Creating impersonated drive service")
        drive_service = GoogleDriveManager.create_impersonated_drive_service(
            json.loads(service_account_key), admin_user.email
        )
        test_id = str(uuid4())
        print(f"Creating shared drive with test ID: {test_id}")
        drive_id = GoogleDriveManager.create_shared_drive(
            drive_service, admin_user.email, test_id
        )
        print(f"Created shared drive with ID: {drive_id}")

        # Setup Onyx infrastructure
        print("Setting up LLM provider")
        LLMProviderManager.create(user_performing_action=admin_user)

        before = datetime.now(timezone.utc)
        print(f"Starting credential creation at: {before}")
        credential: DATestCredential = CredentialManager.create(
            source=DocumentSource.GOOGLE_DRIVE,
            credential_json=credentials,
            user_performing_action=admin_user,
        )
        print(f"Created credential with ID: {credential.id}")

        print("Creating connector")
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
        print(f"Created connector with ID: {connector.id}")

        print("Creating connector-credential pair")
        cc_pair: DATestCCPair = CCPairManager.create(
            credential_id=credential.id,
            connector_id=connector.id,
            access_type=AccessType.SYNC,
            user_performing_action=admin_user,
        )
        print(f"Created CC pair with ID: {cc_pair.id}")

        print("Waiting for initial indexing to complete")
        CCPairManager.wait_for_indexing_completion(
            cc_pair=cc_pair, after=before, user_performing_action=admin_user
        )
        print("Initial indexing completed successfully")

        print("Yielding test environment setup")
        yield drive_service, drive_id, cc_pair, admin_user, test_user_1, test_user_2

    except json.JSONDecodeError:
        print("ERROR: FULL_CONTROL_DRIVE_SERVICE_ACCOUNT is not valid JSON")
        pytest.skip("FULL_CONTROL_DRIVE_SERVICE_ACCOUNT is not valid JSON")
    finally:
        # Cleanup drive and file
        if drive_id is not None:
            print(f"Cleaning up drive with ID: {drive_id}")
            GoogleDriveManager.cleanup_drive(drive_service, drive_id)
            print("Drive cleanup completed")
        print("google_drive_test_env_setup fixture completed")


def test_google_permission_sync(
    reset: None,
    vespa_client: vespa_fixture,
    google_drive_test_env_setup: tuple[
        GoogleDriveService, str, DATestCCPair, DATestUser, DATestUser, DATestUser
    ],
) -> None:
    print("Starting test_google_permission_sync test")
    (
        drive_service,
        drive_id,
        cc_pair,
        admin_user,
        test_user_1,
        test_user_2,
    ) = google_drive_test_env_setup
    print(
        f"Test environment setup retrieved: drive_id={drive_id}, cc_pair_id={cc_pair.id}"
    )

    # ----------------------BASELINE TEST----------------------
    print("\n=== BASELINE TEST ===")
    before = datetime.now(timezone.utc)
    print(f"Starting baseline test at: {before}")

    # Create empty test doc in drive
    print("Creating empty test document")
    doc_id_1 = GoogleDriveManager.create_empty_doc(drive_service, drive_id)
    print(f"Created document with ID: {doc_id_1}")

    # Append text to doc
    doc_text_1 = "The secret number is 12345"
    print(f"Appending text to document: '{doc_text_1}'")
    GoogleDriveManager.append_text_to_doc(drive_service, doc_id_1, doc_text_1)
    print("Text appended successfully")

    # run indexing
    print("Running indexing")
    CCPairManager.run_once(
        cc_pair, from_beginning=True, user_performing_action=admin_user
    )
    print("Waiting for indexing completion")
    CCPairManager.wait_for_indexing_completion(
        cc_pair=cc_pair, after=before, user_performing_action=admin_user
    )
    print("Indexing completed")

    # run permission sync
    print("Running permission sync")
    CCPairManager.sync(
        cc_pair=cc_pair,
        user_performing_action=admin_user,
    )
    print("Waiting for sync completion")
    CCPairManager.wait_for_sync(
        cc_pair=cc_pair,
        after=before,
        number_of_updated_docs=1,
        user_performing_action=admin_user,
    )
    print("Permission sync completed")

    # Verify admin has access to document
    print("Verifying admin access to document")
    admin_results = DocumentSearchManager.search_documents(
        query="secret number", user_performing_action=admin_user
    )
    print(f"Admin search results: {admin_results}")
    assert doc_text_1 in [result.strip("\ufeff") for result in admin_results]
    print("Admin access verified")

    # Verify test_user_1 cannot access document
    print("Verifying test_user_1 cannot access document")
    user1_results = DocumentSearchManager.search_documents(
        query="secret number", user_performing_action=test_user_1
    )
    print(f"User1 search results: {user1_results}")
    assert doc_text_1 not in [result.strip("\ufeff") for result in user1_results]
    print("Verified test_user_1 cannot access document")

    # ----------------------GRANT USER 1 DOC PERMISSIONS TEST--------------------------
    print("\n=== GRANT USER 1 DOC PERMISSIONS TEST ===")
    before = datetime.now(timezone.utc)
    print(f"Starting grant user 1 permissions test at: {before}")

    # Grant user 1 access to document 1
    print(f"Granting user1 ({test_user_1.email}) access to document {doc_id_1}")
    GoogleDriveManager.update_file_permissions(
        drive_service=drive_service,
        file_id=doc_id_1,
        email=test_user_1.email,
        role="reader",
    )
    print("Permission granted successfully")

    # Create a second doc in the drive which user 1 should not have access to
    print("Creating second test document")
    doc_id_2 = GoogleDriveManager.create_empty_doc(drive_service, drive_id)
    print(f"Created second document with ID: {doc_id_2}")
    doc_text_2 = "The secret number is 67890"
    print(f"Appending text to second document: '{doc_text_2}'")
    GoogleDriveManager.append_text_to_doc(drive_service, doc_id_2, doc_text_2)
    print("Text appended successfully to second document")

    # Run indexing
    print("Running indexing for both documents")
    CCPairManager.run_once(
        cc_pair, from_beginning=True, user_performing_action=admin_user
    )
    print("Waiting for indexing completion")
    CCPairManager.wait_for_indexing_completion(
        cc_pair=cc_pair,
        after=before,
        user_performing_action=admin_user,
    )
    print("Indexing completed")

    # Run permission sync
    print("Running permission sync")
    CCPairManager.sync(
        cc_pair=cc_pair,
        user_performing_action=admin_user,
    )
    print("Waiting for sync completion")
    CCPairManager.wait_for_sync(
        cc_pair=cc_pair,
        after=before,
        number_of_updated_docs=1,
        user_performing_action=admin_user,
    )
    print("Permission sync completed")

    # Verify admin can access both documents
    print("Verifying admin access to both documents")
    admin_results = DocumentSearchManager.search_documents(
        query="secret number", user_performing_action=admin_user
    )
    print(f"Admin search results: {admin_results}")
    assert {doc_text_1, doc_text_2} == {
        result.strip("\ufeff") for result in admin_results
    }
    print("Admin access to both documents verified")

    # Verify user 1 can access document 1
    print("Verifying user1 can access document 1")
    user1_results = DocumentSearchManager.search_documents(
        query="secret number", user_performing_action=test_user_1
    )
    print(f"User1 search results: {user1_results}")
    assert doc_text_1 in [result.strip("\ufeff") for result in user1_results]
    print("User1 access to document 1 verified")

    # Verify user 1 cannot access document 2
    print("Verifying user1 cannot access document 2")
    user1_results_2 = DocumentSearchManager.search_documents(
        query="secret number", user_performing_action=test_user_1
    )
    print(f"User1 search results for doc2 check: {user1_results_2}")
    assert doc_text_2 not in [result.strip("\ufeff") for result in user1_results_2]
    print("Verified user1 cannot access document 2")

    # ----------------------REMOVE USER 1 DOC PERMISSIONS TEST--------------------------
    print("\n=== REMOVE USER 1 DOC PERMISSIONS TEST ===")
    before = datetime.now(timezone.utc)
    print(f"Starting remove user 1 permissions test at: {before}")

    # Remove user 1 access to document 1
    print(f"Removing user1 ({test_user_1.email}) access from document {doc_id_1}")
    GoogleDriveManager.remove_file_permissions(
        drive_service=drive_service, file_id=doc_id_1, email=test_user_1.email
    )
    print("Permission removed successfully")

    # Run permission sync
    print("Running permission sync")
    CCPairManager.sync(
        cc_pair=cc_pair,
        user_performing_action=admin_user,
    )
    print("Waiting for sync completion")
    CCPairManager.wait_for_sync(
        cc_pair=cc_pair,
        after=before,
        number_of_updated_docs=1,
        user_performing_action=admin_user,
    )
    print("Permission sync completed")

    # Verify admin can access both documents
    print("Verifying admin access to both documents")
    admin_results = DocumentSearchManager.search_documents(
        query="secret number", user_performing_action=admin_user
    )
    print(f"Admin search results: {admin_results}")
    assert {doc_text_1, doc_text_2} == {
        result.strip("\ufeff") for result in admin_results
    }
    print("Admin access to both documents verified")

    # Verify user 1 cannot access either document
    print("Verifying user1 cannot access any documents")
    user1_results = DocumentSearchManager.search_documents(
        query="secret numbers", user_performing_action=test_user_1
    )
    print(f"User1 search results: {user1_results}")
    assert {result.strip("\ufeff") for result in user1_results} == set()
    print("Verified user1 cannot access any documents")

    # ----------------------GRANT USER 1 DRIVE PERMISSIONS TEST--------------------------
    print("\n=== GRANT USER 1 DRIVE PERMISSIONS TEST ===")
    before = datetime.now(timezone.utc)
    print(f"Starting grant user 1 drive permissions test at: {before}")

    # Grant user 1 access to drive
    print(f"Granting user1 ({test_user_1.email}) access to drive {drive_id}")
    GoogleDriveManager.update_file_permissions(
        drive_service=drive_service,
        file_id=drive_id,
        email=test_user_1.email,
        role="reader",
    )
    print("Drive permission granted successfully")

    # Run permission sync
    print("Running permission sync")
    CCPairManager.sync(
        cc_pair=cc_pair,
        user_performing_action=admin_user,
    )
    print("Waiting for sync completion")
    CCPairManager.wait_for_sync(
        cc_pair=cc_pair,
        after=before,
        number_of_updated_docs=2,
        user_performing_action=admin_user,
        # if we are only updating the group definition for this test we use this varaiable,
        # since it doesn't result in a vespa sync so we don't want to wait for it
        should_wait_for_vespa_sync=False,
    )
    print("Permission sync completed")

    # Verify user 1 can access both documents
    print("Verifying user1 can access both documents")
    user1_results = DocumentSearchManager.search_documents(
        query="secret numbers", user_performing_action=test_user_1
    )
    print(f"User1 search results: {user1_results}")
    assert {doc_text_1, doc_text_2} == {
        result.strip("\ufeff") for result in user1_results
    }
    print("User1 access to both documents verified")

    # ----------------------MAKE DRIVE PUBLIC TEST--------------------------
    print("\n=== MAKE DRIVE PUBLIC TEST ===")
    before = datetime.now(timezone.utc)
    print(f"Starting make drive public test at: {before}")

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
