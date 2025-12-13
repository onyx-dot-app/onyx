from datetime import datetime
from datetime import timezone
from pathlib import Path

from onyx.connectors.models import InputType
from onyx.db.document import get_documents_for_cc_pair
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import AccessType
from onyx.server.documents.models import DocumentSource
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.connector import ConnectorManager
from tests.integration.common_utils.managers.credential import CredentialManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.common_utils.vespa import vespa_fixture


# Use the existing test data directory
TEST_DATA_DIR = (
    Path(__file__).parent.parent.parent.parent
    / "external_dependency_unit"
    / "connectors"
    / "directory"
    / "test_data"
)


def test_directory_connector_indexing(
    reset: None,
    vespa_client: vespa_fixture,
    admin_user: DATestUser,
) -> None:
    """Test that the directory connector can index files from a local directory."""
    before = datetime.now(timezone.utc)

    # Create a credential (directory connector doesn't need credentials, but CC pair requires one)
    credential = CredentialManager.create(
        source=DocumentSource.DIRECTORY,
        credential_json={},
        user_performing_action=admin_user,
    )

    # Create the directory connector
    connector = ConnectorManager.create(
        name="test-directory-connector",
        source=DocumentSource.DIRECTORY,
        input_type=InputType.POLL,
        connector_specific_config={
            "root_directory": str(TEST_DATA_DIR.absolute()),
            "recursive": True,
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

    # Get the indexed documents from the database
    with get_session_with_current_tenant() as db_session:
        documents = get_documents_for_cc_pair(db_session, cc_pair.id)

    # Verify we got documents
    assert len(documents) > 0, "No documents were indexed"

    # Verify we got the expected files
    doc_ids = {doc.id for doc in documents}

    # Should have README.md at top level
    assert any("README.md" in doc_id for doc_id in doc_ids), "Missing README.md"

    # Should have files from subdirectories (recursive=True)
    assert any(
        "code/example.py" in doc_id for doc_id in doc_ids
    ), "Missing code/example.py"
    assert any(
        "documents/notes.txt" in doc_id for doc_id in doc_ids
    ), "Missing documents/notes.txt"

    print(f"Successfully indexed {len(documents)} documents from directory connector")
