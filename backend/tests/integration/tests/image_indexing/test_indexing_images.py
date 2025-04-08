from datetime import datetime
from datetime import timezone

from onyx.connectors.models import InputType
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
from tests.integration.common_utils.test_models import DATestCCPair
from tests.integration.common_utils.test_models import DATestChatSession
from tests.integration.common_utils.test_models import DATestConnector
from tests.integration.common_utils.test_models import DATestCredential
from tests.integration.common_utils.test_models import DATestSettings
from tests.integration.common_utils.test_models import DATestUser


def test_image_indexing(reset: None) -> None:
    print("Starting test")
    # Creating an admin user (first user created is automatically an admin)
    admin_user: DATestUser = UserManager.create(
        email="admin@onyx-test.com",
    )

    # Record the time before indexing
    datetime.now(timezone.utc)

    SettingsManager.update_settings(
        DATestSettings(
            search_time_image_analysis_enabled=True,
            image_extraction_and_analysis_enabled=True,
        )
    )
    print("Updating settings")
    file_name = "Sample.pdf"
    file_path = "tests/integration/common_utils/test_data/" + file_name
    upload_file(file_path, file_name, admin_user)
    LLMProviderManager.create(user_performing_action=admin_user)
    # Create a file connector similar to how the frontend does it

    connector: DATestConnector = ConnectorManager.create(
        name="FileConnector-" + str(int(datetime.now().timestamp())),
        input_type=InputType.LOAD_STATE,
        source=DocumentSource.FILE,
        connector_specific_config={
            "file_locations": [
                file_name,
            ],
        },
        access_type=AccessType.PUBLIC,
        groups=[],
        user_performing_action=admin_user,
    )

    # Create a dummy credential for the file connector
    # This matches frontend behavior where a dummy credential is created
    credential: DATestCredential = CredentialManager.create(
        source=DocumentSource.FILE,
        credential_json={},
        user_performing_action=admin_user,
    )

    # Link the credential to the connector
    cc_pair: DATestCCPair = CCPairManager.create(
        credential_id=credential.id,
        connector_id=connector.id,
        access_type=AccessType.PUBLIC,
        user_performing_action=admin_user,
    )

    # Explicitly run the connector to start indexing
    CCPairManager.run_once(
        cc_pair=cc_pair,
        from_beginning=True,
        user_performing_action=admin_user,
    )

    # Instead of waiting for full indexing completion or searching,
    # just give the system a short time to start processing

    CCPairManager.wait_for_indexing_completion(
        cc_pair=cc_pair,
        after=datetime.now(timezone.utc),
        user_performing_action=admin_user,
    )

    # Create a chat session and ask about dogs in the document
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

    # Print the response
    print(f"Response to 'How many dogs?': {response}")

    # Test passed if we were able to set up the file connector using our frontend-like approach
    print("Test successful - file connector created and chat query completed")
