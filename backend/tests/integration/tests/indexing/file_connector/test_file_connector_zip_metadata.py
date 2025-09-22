import json
import os
from datetime import datetime
from datetime import timezone

import pytest

from onyx.connectors.models import InputType
from onyx.db.document import get_documents_for_cc_pair
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import AccessType
from onyx.server.documents.models import DocumentSource
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.connector import ConnectorManager
from tests.integration.common_utils.managers.credential import CredentialManager
from tests.integration.common_utils.managers.file import FileManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.common_utils.vespa import vespa_fixture


# This is a placeholder - you'll need to create this zip file with actual test files
TEST_FILES_BASE = "tests/integration/tests/indexing/file_connector/test_files"
TEST_META_ZIP_PATH = f"{TEST_FILES_BASE}/with_meta.zip"
TEST_NO_META_ZIP_PATH = f"{TEST_FILES_BASE}/without_meta.zip"
TEST_METADATA_FILE = f"{TEST_FILES_BASE}/.onyx_metadata.json"


@pytest.mark.parametrize(
    "zip_path, has_metadata",
    [
        (TEST_META_ZIP_PATH, True),
        (TEST_NO_META_ZIP_PATH, False),
    ],
)
def test_zip_metadata_handling(
    reset: None,
    vespa_client: vespa_fixture,
    zip_path: str,
    has_metadata: bool,
) -> None:
    before = datetime.now(timezone.utc)
    # Create an admin user
    admin_user: DATestUser = UserManager.create(
        email="admin@onyx-test.com",
    )

    # Upload the test zip file (simulate this happening from frontend)
    upload_response = FileManager.upload_file_for_connector(
        file_path=zip_path,
        file_name=os.path.basename(zip_path),
        user_performing_action=admin_user,
        content_type="application/zip",
    )

    file_paths = upload_response.file_paths
    assert file_paths, "File upload failed - no file paths returned"
    if has_metadata:
        metadata = upload_response.zip_metadata
        assert metadata, "Metadata should be present"
    else:
        metadata = {}

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
        connector_specific_config={
            "file_locations": file_paths,
            "file_names": [os.path.basename(file_path) for file_path in file_paths],
            "zip_metadata": metadata,
        },
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

    # Run the connector to index the files
    CCPairManager.run_once(
        cc_pair, from_beginning=True, user_performing_action=admin_user
    )
    CCPairManager.wait_for_indexing_completion(
        cc_pair=cc_pair, after=before, user_performing_action=admin_user
    )

    # Get the indexed documents
    with get_session_with_current_tenant() as db_session:
        documents = get_documents_for_cc_pair(db_session, cc_pair.id)

    # Expected metadata from the .onyx_metadata.json file
    with open(TEST_METADATA_FILE, "r") as f:
        expected_metadata = json.load(f)

    # Verify each document has the correct metadata
    for doc in documents:
        filename = doc.semantic_id
        if filename in expected_metadata:
            expected = expected_metadata[filename]
            assert (
                doc.semantic_id == expected["display_name"]
            ), f"Display name mismatch for {filename}"
            assert doc.link == expected["link"], f"Link mismatch for {filename}"
