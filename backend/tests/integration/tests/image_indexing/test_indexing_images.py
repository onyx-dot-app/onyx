import os
from datetime import datetime
from datetime import timezone

import pytest

from onyx.connectors.models import InputType
from onyx.db.engine import get_session_context_manager
from onyx.db.enums import AccessType
from onyx.server.documents.models import DocumentSource
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.connector import ConnectorManager
from tests.integration.common_utils.managers.credential import CredentialManager
from tests.integration.common_utils.managers.document import DocumentManager
from tests.integration.common_utils.managers.file import FileManager
from tests.integration.common_utils.managers.settings import SettingsManager
from tests.integration.common_utils.test_models import DATestSettings
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.common_utils.vespa import vespa_fixture

FILE_NAME = "Sample.pdf"
FILE_PATH = "tests/integration/common_utils/test_files"


def test_image_indexing(
    reset: None,
    admin_user: DATestUser,
    vespa_client: vespa_fixture,
) -> None:
    os.makedirs(FILE_PATH, exist_ok=True)
    test_file_path = os.path.join(FILE_PATH, FILE_NAME)

    # Use FileManager to upload the test file
    upload_response = FileManager.upload_file_for_connector(
        file_path=test_file_path, file_name=FILE_NAME, user_performing_action=admin_user
    )

    SettingsManager.update_settings(
        DATestSettings(
            search_time_image_analysis_enabled=True,
            image_extraction_and_analysis_enabled=True,
        ),
        user_performing_action=admin_user,
    )

    file_paths = upload_response.file_paths

    if not file_paths:
        pytest.fail("File upload failed - no file paths returned")

    # Create a dummy credential for the file connector
    credential = CredentialManager.create(
        source=DocumentSource.FILE,
        credential_json={},
        user_performing_action=admin_user,
    )

    # Create the connector
    connector_name = f"FileConnector-{int(datetime.now().timestamp())}"
    connector = ConnectorManager.create(
        name=connector_name,
        source=DocumentSource.FILE,
        input_type=InputType.LOAD_STATE,
        connector_specific_config={"file_locations": file_paths, "zip_metadata": {}},
        access_type=AccessType.PUBLIC,
        groups=[],
        user_performing_action=admin_user,
    )

    # Link the credential to the connector
    cc_pair = CCPairManager.create(
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
    CCPairManager.wait_for_indexing_completion(
        cc_pair=cc_pair,
        after=datetime.now(timezone.utc),
        user_performing_action=admin_user,
    )

    with get_session_context_manager() as db_session:
        documents = DocumentManager.fetch_documents_for_cc_pair(
            cc_pair_id=cc_pair.id,
            db_session=db_session,
            vespa_client=vespa_client,
        )

        assert len(documents) == 1
        document = documents[0]
        assert document.image_file_id is not None
        assert document.image_file_id == file_paths[0]
