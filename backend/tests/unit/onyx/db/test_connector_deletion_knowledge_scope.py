"""Exercise connector cleanup and search scoping without external services."""

from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.connector_credential_pair import (
    delete_connector_credential_pair__no_commit,
)
from onyx.db.document import delete_documents__no_commit
from onyx.db.document import delete_documents_by_connector_credential_pair__no_commit
from onyx.db.models import Persona__Document
from onyx.db.models import Persona__HierarchyNode
from onyx.db.models import Persona__Tool
from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.opensearch.schema import ANCESTOR_HIERARCHY_NODE_IDS_FIELD_NAME
from onyx.document_index.opensearch.search import DocumentQuery
from onyx.server.documents.models import ConnectorCredentialPairIdentifier
from onyx.tools.constants import SEARCH_TOOL_ID


@pytest.fixture
def cleanup_session() -> Generator[Session, None, None]:
    # These operations only read association keys. A small SQLite schema runs
    # the real cleanup SQL without requiring Onyx's external services.
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.exec_driver_sql(
            "CREATE TABLE connector_credential_pair (id INTEGER PRIMARY KEY, "
            "connector_id INTEGER NOT NULL, credential_id INTEGER NOT NULL, "
            "UNIQUE(connector_id, credential_id))"
        )
        connection.exec_driver_sql(
            "CREATE TABLE hierarchy_node_by_connector_credential_pair ("
            "hierarchy_node_id INTEGER NOT NULL, connector_id INTEGER NOT NULL, "
            "credential_id INTEGER NOT NULL, "
            "PRIMARY KEY(hierarchy_node_id, connector_id, credential_id), "
            "FOREIGN KEY(connector_id, credential_id) REFERENCES "
            "connector_credential_pair(connector_id, credential_id) ON DELETE CASCADE)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE tool (id INTEGER PRIMARY KEY, in_code_tool_id TEXT)"
        )
        connection.exec_driver_sql("CREATE TABLE document (id TEXT PRIMARY KEY)")
        connection.exec_driver_sql("INSERT INTO document VALUES ('10'), ('20')")
        connection.exec_driver_sql(
            "CREATE TABLE document_by_connector_credential_pair ("
            "id TEXT NOT NULL REFERENCES document(id) ON DELETE CASCADE, "
            "connector_id INTEGER NOT NULL, credential_id INTEGER NOT NULL, "
            "PRIMARY KEY(id, connector_id, credential_id))"
        )
        for table_name, key_name in (
            ("persona__hierarchy_node", "hierarchy_node_id"),
            ("persona__tool", "tool_id"),
            ("persona__document", "document_id"),
            ("persona__document_set", "document_set_id"),
            ("persona__user_file", "user_file_id"),
        ):
            document_reference = (
                " REFERENCES document(id) ON DELETE CASCADE"
                if key_name == "document_id"
                else ""
            )
            key_type = "TEXT" if key_name == "document_id" else "INTEGER"
            connection.exec_driver_sql(
                f"CREATE TABLE {table_name} (persona_id INTEGER NOT NULL, "
                f"{key_name} {key_type} NOT NULL{document_reference}, "
                f"PRIMARY KEY(persona_id, {key_name}))"
            )
        connection.exec_driver_sql(
            "INSERT INTO tool VALUES (1, ?), (2, NULL)", (SEARCH_TOOL_ID,)
        )
        connection.exec_driver_sql(
            "INSERT INTO connector_credential_pair VALUES (1, 1, 1)"
        )
        connection.exec_driver_sql(
            "INSERT INTO hierarchy_node_by_connector_credential_pair VALUES (10, 1, 1)"
        )
        connection.exec_driver_sql(
            "INSERT INTO persona__hierarchy_node VALUES (100, 10)"
        )
        connection.exec_driver_sql(
            "INSERT INTO persona__tool VALUES (100, 1), (100, 2), (200, 1)"
        )
    try:
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()


def test_deleting_final_folder_does_not_enable_unrestricted_search(
    cleanup_session: Session,
) -> None:
    delete_connector_credential_pair__no_commit(cleanup_session, 1, 1)
    cleanup_session.commit()

    node_ids = list(
        cleanup_session.scalars(
            select(Persona__HierarchyNode.hierarchy_node_id).where(
                Persona__HierarchyNode.persona_id == 100
            )
        )
    )
    filters = DocumentQuery._get_search_filters(
        tenant_state=TenantState(tenant_id="public", multitenant=False),
        include_hidden=False,
        access_control_list=["user_email:test@example.com"],
        source_types=[],
        tags=[],
        document_sets=[],
        project_id_filter=None,
        persona_id_filter=None,
        time_cutoff=None,
        min_chunk_index=None,
        max_chunk_index=None,
        hierarchy_node_ids=node_ids or None,
    )
    tool_ids = set(
        cleanup_session.scalars(
            select(Persona__Tool.tool_id).where(Persona__Tool.persona_id == 100)
        )
    )
    assert node_ids == []
    assert ANCESTOR_HIERARCHY_NODE_IDS_FIELD_NAME in str(filters) or 1 not in tool_ids
    assert tool_ids == {2}  # Other actions remain available.
    assert (
        cleanup_session.scalar(
            select(Persona__Tool.tool_id).where(Persona__Tool.persona_id == 200)
        )
        == 1
    )  # Intentionally unscoped assistants are unaffected.


@pytest.mark.parametrize(
    "remaining_knowledge_table",
    [
        "persona__hierarchy_node",
        "persona__document",
        "persona__document_set",
        "persona__user_file",
    ],
)
def test_deleting_folder_preserves_search_with_other_knowledge(
    cleanup_session: Session, remaining_knowledge_table: str
) -> None:
    cleanup_session.connection().exec_driver_sql(
        f"INSERT INTO {remaining_knowledge_table} VALUES (100, 20)"
    )
    delete_connector_credential_pair__no_commit(cleanup_session, 1, 1)
    cleanup_session.commit()

    assert set(
        cleanup_session.scalars(
            select(Persona__Tool.tool_id).where(Persona__Tool.persona_id == 100)
        )
    ) == {1, 2}


@pytest.mark.parametrize(
    "remaining_knowledge_table",
    [
        None,
        "persona__hierarchy_node",
        "persona__document",
        "persona__document_set",
        "persona__user_file",
    ],
)
def test_deleting_last_attached_document_keeps_search_scoped(
    cleanup_session: Session, remaining_knowledge_table: str | None
) -> None:
    cleanup_session.connection().exec_driver_sql(
        "DELETE FROM persona__hierarchy_node WHERE persona_id = 100"
    )
    cleanup_session.connection().exec_driver_sql(
        "INSERT INTO persona__document VALUES (100, '10')"
    )
    if remaining_knowledge_table is not None:
        cleanup_session.connection().exec_driver_sql(
            f"INSERT INTO {remaining_knowledge_table} VALUES (100, 20)"
        )

    delete_documents__no_commit(cleanup_session, ["10"])
    cleanup_session.commit()

    assert (
        list(
            cleanup_session.scalars(
                select(Persona__Document.document_id).where(
                    Persona__Document.persona_id == 100,
                    Persona__Document.document_id == "10",
                )
            )
        )
        == []
    )
    assert set(
        cleanup_session.scalars(
            select(Persona__Tool.tool_id).where(Persona__Tool.persona_id == 100)
        )
    ) == ({2} if remaining_knowledge_table is None else {1, 2})
    assert (
        cleanup_session.scalar(
            select(Persona__Tool.tool_id).where(Persona__Tool.persona_id == 200)
        )
        == 1
    )  # Intentionally unscoped assistants remain available.


def test_unlinking_shared_document_preserves_attachment_and_search(
    cleanup_session: Session,
) -> None:
    cleanup_session.connection().exec_driver_sql(
        "DELETE FROM persona__hierarchy_node WHERE persona_id = 100"
    )
    cleanup_session.connection().exec_driver_sql(
        "INSERT INTO persona__document VALUES (100, '10')"
    )
    cleanup_session.connection().exec_driver_sql(
        "INSERT INTO document_by_connector_credential_pair "
        "VALUES ('10', 1, 1), ('10', 2, 2)"
    )

    delete_documents_by_connector_credential_pair__no_commit(
        cleanup_session,
        ["10"],
        ConnectorCredentialPairIdentifier(connector_id=1, credential_id=1),
    )
    delete_connector_credential_pair__no_commit(cleanup_session, 1, 1)
    cleanup_session.commit()

    assert (
        cleanup_session.scalar(
            select(Persona__Document.document_id).where(
                Persona__Document.persona_id == 100
            )
        )
        == "10"
    )
    assert set(
        cleanup_session.scalars(
            select(Persona__Tool.tool_id).where(Persona__Tool.persona_id == 100)
        )
    ) == {1, 2}
