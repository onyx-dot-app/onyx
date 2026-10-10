from io import BytesIO
from uuid import uuid4

from PIL import Image

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import UserFileStatus
from onyx.db.models import Document, UserFile
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.document_index import DocumentIndexClient
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.api_key import APIKeyManager
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.document import IngestionManager
from tests.integration.common_utils.managers.project import ProjectManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser


def test_ingestion_api_crud(
    reset: None,  # noqa: ARG001
    document_index_client: DocumentIndexClient,
) -> None:
    """Test create, list, and delete via the ingestion API."""
    admin_user: DATestUser = UserManager.create(email="admin@onyx.app")
    cc_pair = CCPairManager.create_from_scratch(
        name="Ingestion-API-Test",
        source=DocumentSource.FILE,
        input_type=InputType.LOAD_STATE,
        connector_specific_config={
            "file_locations": [],
            "file_names": [],
            "zip_metadata_file_id": None,
        },
        user_performing_action=admin_user,
    )
    api_key = APIKeyManager.create(user_performing_action=admin_user)
    api_key.headers.update(admin_user.headers)

    # CREATE
    doc = IngestionManager.seed_doc_with_content(
        cc_pair=cc_pair,
        content="Test document",
        document_id="test-doc-1",
        api_key=api_key,
    )

    with get_session_with_current_tenant() as db_session:
        doc_db = db_session.query(Document).filter(Document.id == doc.id).first()
        assert doc_db is not None
        assert doc_db.from_ingestion_api is True

    chunks = document_index_client.get_chunks_by_document_id([doc.id])
    assert len(chunks) == 1

    # LIST
    docs_list = IngestionManager.list_all_ingestion_docs(api_key=api_key)
    assert any(d["document_id"] == doc.id for d in docs_list)

    # DELETE
    IngestionManager.delete(document_id=doc.id, api_key=api_key)

    with get_session_with_current_tenant() as db_session:
        doc_db = db_session.query(Document).filter(Document.id == doc.id).first()
        assert doc_db is None

    chunks = document_index_client.get_chunks_by_document_id([doc.id])
    assert len(chunks) == 0


def test_ingestion_accepts_image_uploaded_with_skip_indexing(
    admin_user: DATestUser,
) -> None:
    """An image uploaded with skip_indexing is stored as SKIPPED, is not indexed,
    and still passes the ingestion check that the caller owns the image."""
    image = BytesIO()
    Image.new("RGB", (8, 8), color="blue").save(image, format="PNG")
    uploaded = ProjectManager.upload_files(
        project_id=None,
        files=[("diagram.png", image.getvalue())],
        user_performing_action=admin_user,
        skip_indexing=True,
    )
    assert not uploaded.rejected_files
    assert len(uploaded.user_files) == 1
    user_file = uploaded.user_files[0]
    assert user_file.status == UserFileStatus.SKIPPED

    cc_pair = CCPairManager.create_from_scratch(
        name=f"Ingestion-Skip-Indexing-{uuid4()}",
        source=DocumentSource.FILE,
        input_type=InputType.LOAD_STATE,
        connector_specific_config={
            "file_locations": [],
            "file_names": [],
            "zip_metadata_file_id": None,
        },
        user_performing_action=admin_user,
    )
    document_id = f"skip-indexing-{uuid4()}"
    response = client.post(
        f"{API_SERVER_URL}/onyx-api/ingestion",
        json={
            "document": {
                "id": document_id,
                "semantic_identifier": "Diagram",
                "metadata": {},
                "source": DocumentSource.FILE,
                "sections": [
                    {
                        "image_file_id": user_file.file_id,
                        "link": f"https://example.com/{document_id}",
                    }
                ],
            },
            "cc_pair_id": cc_pair.id,
        },
        headers=admin_user.headers,
    )
    assert response.status_code == 200, response.text

    with get_session_with_current_tenant() as db_session:
        assert db_session.get(Document, document_id) is not None
        stored_file = db_session.get(UserFile, user_file.id)
        assert stored_file is not None
        assert stored_file.status == UserFileStatus.SKIPPED
