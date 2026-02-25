from pytest import MonkeyPatch

from onyx.access.models import ExternalAccess
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentSource
from onyx.connectors.models import HierarchyNode
from onyx.connectors.models import IndexAttemptMetadata
from onyx.connectors.models import TextSection
from onyx.db.enums import HierarchyNodeType
from onyx.indexing import indexing_pipeline
from onyx.indexing.postgres_sanitization import sanitize_document_for_postgres
from onyx.indexing.postgres_sanitization import sanitize_hierarchy_node_for_postgres


def test_sanitize_document_for_postgres_removes_nul_bytes() -> None:
    document = Document(
        id="doc\x00-id",
        source=DocumentSource.FILE,
        semantic_identifier="sem\x00-id",
        title="ti\x00tle",
        parent_hierarchy_raw_node_id="parent\x00-id",
        sections=[TextSection(link="lin\x00k", text="te\x00xt")],
        metadata={"ke\x00y": "va\x00lue", "list\x00key": ["a\x00", "b"]},
        doc_metadata={
            "j\x00son": {
                "in\x00ner": "va\x00l",
                "arr": ["x\x00", {"dee\x00p": "y\x00"}],
            }
        },
        primary_owners=[BasicExpertInfo(display_name="Ali\x00ce", email="a\x00@x.com")],
        secondary_owners=[BasicExpertInfo(first_name="Bo\x00b", last_name="Sm\x00ith")],
        external_access=ExternalAccess(
            external_user_emails={"user\x00@example.com"},
            external_user_group_ids={"gro\x00up-1"},
            is_public=False,
        ),
    )

    sanitized = sanitize_document_for_postgres(document)

    assert sanitized.id == "doc-id"
    assert sanitized.semantic_identifier == "sem-id"
    assert sanitized.title == "title"
    assert sanitized.parent_hierarchy_raw_node_id == "parent-id"
    assert sanitized.sections[0].link == "link"
    assert sanitized.sections[0].text == "text"
    assert sanitized.metadata == {"key": "value", "listkey": ["a", "b"]}
    assert sanitized.doc_metadata == {
        "json": {"inner": "val", "arr": ["x", {"deep": "y"}]}
    }
    assert sanitized.primary_owners is not None
    assert sanitized.primary_owners[0].display_name == "Alice"
    assert sanitized.primary_owners[0].email == "a@x.com"
    assert sanitized.secondary_owners is not None
    assert sanitized.secondary_owners[0].first_name == "Bob"
    assert sanitized.secondary_owners[0].last_name == "Smith"
    assert sanitized.external_access is not None
    assert sanitized.external_access.external_user_emails == {"user@example.com"}
    assert sanitized.external_access.external_user_group_ids == {"group-1"}

    # Ensure original document is not mutated
    assert document.id == "doc\x00-id"
    assert document.metadata == {"ke\x00y": "va\x00lue", "list\x00key": ["a\x00", "b"]}


def test_sanitize_hierarchy_node_for_postgres_removes_nul_bytes() -> None:
    node = HierarchyNode(
        raw_node_id="raw\x00-id",
        raw_parent_id="paren\x00t-id",
        display_name="fol\x00der",
        link="https://exa\x00mple.com",
        node_type=HierarchyNodeType.FOLDER,
        external_access=ExternalAccess(
            external_user_emails={"a\x00@example.com"},
            external_user_group_ids={"g\x00-1"},
            is_public=True,
        ),
    )

    sanitized = sanitize_hierarchy_node_for_postgres(node)

    assert sanitized.raw_node_id == "raw-id"
    assert sanitized.raw_parent_id == "parent-id"
    assert sanitized.display_name == "folder"
    assert sanitized.link == "https://example.com"
    assert sanitized.external_access is not None
    assert sanitized.external_access.external_user_emails == {"a@example.com"}
    assert sanitized.external_access.external_user_group_ids == {"g-1"}


def test_index_doc_batch_prepare_sanitizes_before_db_ops(
    monkeypatch: MonkeyPatch,
) -> None:
    document = Document(
        id="doc\x00id",
        source=DocumentSource.FILE,
        semantic_identifier="sem\x00id",
        sections=[TextSection(text="content", link="li\x00nk")],
        metadata={"ke\x00y": "va\x00lue"},
    )

    captured: dict[str, object] = {}

    def _get_documents_by_ids(db_session: object, document_ids: list[str]) -> list:
        _ = db_session, document_ids
        return []

    monkeypatch.setattr(
        indexing_pipeline, "get_documents_by_ids", _get_documents_by_ids
    )

    def _capture_upsert_documents_in_db(**kwargs: object) -> None:
        captured["upsert_documents"] = kwargs["documents"]

    monkeypatch.setattr(
        indexing_pipeline, "_upsert_documents_in_db", _capture_upsert_documents_in_db
    )

    def _capture_doc_cc_pair(*args: object) -> None:
        captured["cc_pair_doc_ids"] = args[3]

    monkeypatch.setattr(
        indexing_pipeline,
        "upsert_document_by_connector_credential_pair",
        _capture_doc_cc_pair,
    )

    def _noop_link_hierarchy_nodes_to_documents(
        db_session: object,
        document_ids: list[str],
        source: DocumentSource,
        commit: bool,
    ) -> int:
        _ = db_session, document_ids, source, commit
        return 0

    monkeypatch.setattr(
        indexing_pipeline,
        "link_hierarchy_nodes_to_documents",
        _noop_link_hierarchy_nodes_to_documents,
    )

    context = indexing_pipeline.index_doc_batch_prepare(
        documents=[document],
        index_attempt_metadata=IndexAttemptMetadata(connector_id=1, credential_id=2),
        db_session=object(),  # type: ignore[arg-type]
        ignore_time_skip=True,
    )

    assert context is not None
    assert context.updatable_docs[0].id == "docid"
    assert context.updatable_docs[0].semantic_identifier == "semid"
    assert context.updatable_docs[0].metadata == {"key": "value"}
    assert captured["cc_pair_doc_ids"] == ["docid"]

    upsert_documents = captured["upsert_documents"]
    assert isinstance(upsert_documents, list)
    assert upsert_documents[0].id == "docid"
