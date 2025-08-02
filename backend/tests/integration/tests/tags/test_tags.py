from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import Document
from onyx.db.tag import get_structured_tags_for_document
from tests.integration.common_utils.managers.api_key import APIKeyManager
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.document import DocumentManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser


def test_tag_creation_and_update(reset: None) -> None:
    # create admin user
    admin_user: DATestUser = UserManager.create(email="admin@onyx.app")

    # create a minimal file connector
    cc_pair = CCPairManager.create_from_scratch(
        name="KG-Test-FileConnector",
        source=DocumentSource.FILE,
        input_type=InputType.LOAD_STATE,
        connector_specific_config={
            "file_locations": [],
            "file_names": [],
            "zip_metadata": {},
        },
        user_performing_action=admin_user,
    )
    api_key = APIKeyManager.create(user_performing_action=admin_user)
    api_key.headers.update(admin_user.headers)
    LLMProviderManager.create(user_performing_action=admin_user)

    # create document
    doc1_expected_metadata: dict[str, str | list[str]] = {
        "value": "val",
        "multiple_list": ["a", "b", "c"],
        "single_list": ["x"],
    }
    doc1_expected_tags: set[tuple[str, str, bool]] = {
        ("value", "val", False),
        ("multiple_list", "a", True),
        ("multiple_list", "b", True),
        ("multiple_list", "c", True),
        ("single_list", "x", True),
    }
    doc1 = DocumentManager.seed_doc_with_content(
        cc_pair=cc_pair,
        content="Dummy content",
        document_id="doc1",
        metadata=doc1_expected_metadata,
        api_key=api_key,
    )

    # these are added by the connector
    doc1_expected_metadata["document_id"] = "doc1"
    doc1_expected_tags.add(("document_id", "doc1", False))

    # get document from db
    with get_session_with_current_tenant() as db_session:
        doc1_db = db_session.query(Document).filter(Document.id == doc1.id).first()
        assert doc1_db is not None
        assert doc1_db.id == doc1.id

        doc1_tags = doc1_db.tags

    # check tags
    doc1_tags_data: set[tuple[str, str, bool]] = {
        (tag.tag_key, tag.tag_value, tag.is_list) for tag in doc1_tags
    }
    assert doc1_tags_data == doc1_expected_tags

    # check structured tags
    with get_session_with_current_tenant() as db_session:
        doc1_metadata = get_structured_tags_for_document(doc1.id, db_session)
    assert doc1_metadata == doc1_expected_metadata

    # update metadata
    doc1_new_expected_metadata: dict[str, str | list[str]] = {
        "value": "val2",
        "multiple_list": ["a", "d"],
        "new_value": "new_val",
    }
    doc1_new_expected_tags: set[tuple[str, str, bool]] = {
        ("value", "val2", False),
        ("multiple_list", "a", True),
        ("multiple_list", "d", True),
        ("new_value", "new_val", False),
    }
    doc1_new = DocumentManager.seed_doc_with_content(
        cc_pair=cc_pair,
        content="Dummy content",
        document_id="doc1",
        metadata=doc1_new_expected_metadata,
        api_key=api_key,
    )
    assert doc1_new.id == doc1.id

    # these are added by the connector
    doc1_new_expected_metadata["document_id"] = "doc1"
    doc1_new_expected_tags.add(("document_id", "doc1", False))

    # get new document from db
    with get_session_with_current_tenant() as db_session:
        doc1_new_db = db_session.query(Document).filter(Document.id == doc1.id).first()
        assert doc1_new_db is not None
        assert doc1_new_db.id == doc1.id

        doc1_new_tags = doc1_new_db.tags

    # check tags
    doc1_new_tags_data: set[tuple[str, str, bool]] = {
        (tag.tag_key, tag.tag_value, tag.is_list) for tag in doc1_new_tags
    }
    assert doc1_new_tags_data == doc1_new_expected_tags

    # check structured tags
    with get_session_with_current_tenant() as db_session:
        doc1_new_metadata = get_structured_tags_for_document(doc1.id, db_session)
    assert doc1_new_metadata == doc1_new_expected_metadata


def test_tag_sharing(reset: None) -> None:
    # create admin user
    admin_user: DATestUser = UserManager.create(email="admin@onyx.app")

    # create a minimal file connector
    cc_pair = CCPairManager.create_from_scratch(
        name="KG-Test-FileConnector",
        source=DocumentSource.FILE,
        input_type=InputType.LOAD_STATE,
        connector_specific_config={
            "file_locations": [],
            "file_names": [],
            "zip_metadata": {},
        },
        user_performing_action=admin_user,
    )
    api_key = APIKeyManager.create(user_performing_action=admin_user)
    api_key.headers.update(admin_user.headers)
    LLMProviderManager.create(user_performing_action=admin_user)

    # create documents
    doc1_expected_metadata: dict[str, str | list[str]] = {
        "value": "val",
        "list": ["a", "b"],
        "same_key": "x",
    }
    doc1_expected_tags: set[tuple[str, str, bool]] = {
        ("value", "val", False),
        ("list", "a", True),
        ("list", "b", True),
        ("same_key", "x", False),
    }
    doc1 = DocumentManager.seed_doc_with_content(
        cc_pair=cc_pair,
        content="Dummy content",
        document_id="doc1",
        metadata=doc1_expected_metadata,
        api_key=api_key,
    )

    doc2_expected_metadata: dict[str, str | list[str]] = {
        "value": "val",
        "list": ["a", "c"],
        "same_key": ["x"],
    }
    doc2_expected_tags: set[tuple[str, str, bool]] = {
        ("value", "val", False),
        ("list", "a", True),
        ("list", "c", True),
        ("same_key", "x", True),
    }
    doc2 = DocumentManager.seed_doc_with_content(
        cc_pair=cc_pair,
        content="Dummy content",
        document_id="doc2",
        metadata=doc2_expected_metadata,
        api_key=api_key,
    )

    # these are added by the connector
    doc1_expected_metadata["document_id"] = "doc1"
    doc1_expected_tags.add(("document_id", "doc1", False))
    doc2_expected_metadata["document_id"] = "doc2"
    doc2_expected_tags.add(("document_id", "doc2", False))

    # get documents from db
    with get_session_with_current_tenant() as db_session:
        doc1_db = db_session.query(Document).filter(Document.id == doc1.id).first()
        doc2_db = db_session.query(Document).filter(Document.id == doc2.id).first()
        assert doc1_db is not None
        assert doc1_db.id == doc1.id
        assert doc2_db is not None
        assert doc2_db.id == doc2.id

        doc1_tags = doc1_db.tags
        doc2_tags = doc2_db.tags

    # check tags
    doc1_tags_data: set[tuple[str, str, bool]] = {
        (tag.tag_key, tag.tag_value, tag.is_list) for tag in doc1_tags
    }
    assert doc1_tags_data == doc1_expected_tags

    doc2_tags_data: set[tuple[str, str, bool]] = {
        (tag.tag_key, tag.tag_value, tag.is_list) for tag in doc2_tags
    }
    assert doc2_tags_data == doc2_expected_tags

    # check tag sharing
    doc1_tagkv_id: dict[tuple[str, str], int] = {
        (tag.tag_key, tag.tag_value): tag.id for tag in doc1_tags
    }
    doc2_tagkv_id: dict[tuple[str, str], int] = {
        (tag.tag_key, tag.tag_value): tag.id for tag in doc2_tags
    }
    assert doc1_tagkv_id[("value", "val")] == doc2_tagkv_id[("value", "val")]
    assert doc1_tagkv_id[("list", "a")] == doc2_tagkv_id[("list", "a")]
    assert doc1_tagkv_id[("same_key", "x")] != doc2_tagkv_id[("same_key", "x")]
