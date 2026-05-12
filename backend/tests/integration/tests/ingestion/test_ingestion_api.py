from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import Document
from tests.integration.common_utils.managers.api_key import APIKeyManager
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.document import IngestionManager
from tests.integration.common_utils.managers.document_search import (
    DocumentSearchManager,
)
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.common_utils.vespa import vespa_fixture


def test_ingestion_api_crud(
    reset: None,  # noqa: ARG001
    vespa_client: vespa_fixture,
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

    vespa_docs = vespa_client.get_documents_by_id([doc.id])["documents"]
    assert len(vespa_docs) == 1

    # LIST
    docs_list = IngestionManager.list_all_ingestion_docs(api_key=api_key)
    assert any(d["document_id"] == doc.id for d in docs_list)

    # DELETE
    IngestionManager.delete(document_id=doc.id, api_key=api_key)

    with get_session_with_current_tenant() as db_session:
        doc_db = db_session.query(Document).filter(Document.id == doc.id).first()
        assert doc_db is None

    vespa_docs = vespa_client.get_documents_by_id([doc.id])["documents"]
    assert len(vespa_docs) == 0


def test_ingestion_api_doc_is_searchable(
    reset: None,  # noqa: ARG001
    vespa_client: vespa_fixture,
) -> None:
    """Regression test for ENG-3387: documents created via the ingestion API
    must appear in search results, not just exist in Vespa.

    The existing CRUD test only verifies that the doc lands in Postgres and
    Vespa. The original bug was that ingested docs were stored correctly but
    were never returned by user-facing search — typically because the cc_pair
    lacked the PUBLIC access type or the doc's ACL was misconfigured.
    """
    admin_user: DATestUser = UserManager.create(email="admin@onyx.app")
    cc_pair = CCPairManager.create_from_scratch(
        name="Ingestion-Search-Test",
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

    # Distinctive content the search query can latch onto; a UUID-like
    # token keeps the assertion deterministic against any seed corpus that
    # might exist in the test environment.
    distinctive_phrase = "platypus chartreuse 7f3a91-ingestion-eng3387"
    doc = IngestionManager.seed_doc_with_content(
        cc_pair=cc_pair,
        content=f"This document mentions {distinctive_phrase} once.",
        document_id="eng3387-searchable-doc",
        api_key=api_key,
    )

    # Sanity check that the indexing pipeline did write to Vespa — if this
    # fails the bug is somewhere upstream of search.
    vespa_docs = vespa_client.get_documents_by_id([doc.id])["documents"]
    assert len(vespa_docs) == 1, (
        "ingested doc never reached Vespa — bug is in the indexing pipeline, "
        "not the search-time ACL filter"
    )

    # The actual ENG-3387 assertion: a user who has access to the cc_pair
    # should see this doc returned by /search/send-search-message.
    matching_blurbs = DocumentSearchManager.search_documents(
        query=distinctive_phrase,
        user_performing_action=admin_user,
    )
    assert any(distinctive_phrase in blurb for blurb in matching_blurbs), (
        f"Ingested document was indexed in Vespa but did not surface in search "
        f"results for the same admin user. ACL or doc-set filtering is dropping "
        f"it at query time. Got blurbs: {matching_blurbs!r}"
    )
