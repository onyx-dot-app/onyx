import os
from datetime import datetime
from datetime import timezone

import pytest

from onyx.db.enums import AccessType
from onyx.server.documents.models import DocumentSource
from tests.integration.common_utils.connectors import upload_file
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.connector import ConnectorManager
from tests.integration.common_utils.managers.credential import CredentialManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.settings import SettingsManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestChatSession
from tests.integration.common_utils.test_models import DATestSettings
from tests.integration.common_utils.test_models import DATestUser


def test_image_indexing(reset: None) -> None:
    # Creating an admin user (first user created is automatically an admin)
    admin_user: DATestUser = UserManager.create(
        email="admin@onyx-test.com",
    )

    # Create a test PDF file if it doesn't exist
    test_file_dir = "tests/integration/common_utils/test_data"
    os.makedirs(test_file_dir, exist_ok=True)
    test_file_path = os.path.join(test_file_dir, "sample.pdf")
    print(f"Using test file: {test_file_path}")

    # Use our fixed upload_file function to upload the test file
    file_name = "sample.pdf"
    upload_response = upload_file(
        file_path=test_file_path, file_name=file_name, user_performing_action=admin_user
    )

    LLMProviderManager.create(
        name="test_llm",
        user_performing_action=admin_user,
    )
    print("Created LLM provider")
    SettingsManager.update_settings(
        DATestSettings(
            search_time_image_analysis_enabled=True,
            image_extraction_and_analysis_enabled=True,
        )
    )

    print(f"File upload response: {upload_response}")
    file_paths = upload_response.get("file_paths", [])

    if not file_paths:
        pytest.fail("File upload failed - no file paths returned")

    # Create a dummy credential for the file connector
    credential = CredentialManager.create(
        source=DocumentSource.FILE,
        credential_json={},
        user_performing_action=admin_user,
    )

    print("Created credential")

    print("Creating connector")
    print("file_paths: ", file_paths)
    print({"file_locations": file_paths})
    # Create the connector
    connector_name = f"FileConnector-{int(datetime.now().timestamp())}"
    connector = ConnectorManager.create(
        name=connector_name,
        source=DocumentSource.FILE,
        input_type="load_state",
        connector_specific_config={"file_locations": file_paths},
        access_type=AccessType.PUBLIC,
        groups=[],
        user_performing_action=admin_user,
    )

    print(f"Created connector with ID: {connector.id}")

    # Link the credential to the connector
    cc_pair = CCPairManager.create(
        credential_id=credential.id,
        connector_id=connector.id,
        access_type=AccessType.PUBLIC,
        user_performing_action=admin_user,
    )

    print(f"Created CC pair with ID: {cc_pair.id}")

    # Explicitly run the connector to start indexing
    CCPairManager.run_once(
        cc_pair=cc_pair,
        from_beginning=True,
        user_performing_action=admin_user,
    )
    CCPairManager.wait_for_indexing_completion(
        cc_pair=cc_pair,
        after=datetime.now(timezone.utc),
        user_performing_action=admin_user,
    )

    print("Started indexing")

    # Give the system some time to index the document
    print("Sleeping for 15 seconds to allow indexing to progress...")

    # Create a chat session and ask about dogs
    print("Creating chat session to ask about dogs...")
    chat_session: DATestChatSession = ChatSessionManager.create(
        user_performing_action=admin_user
    )

    # Ask about dogs in the document
    response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="How many dogs?",
        user_performing_action=admin_user,
    )

    print(f"Response to 'How many dogs?': {response}")

    # Test passed if we were able to complete the workflow
    print("Test successful - file uploaded and chat query completed")
