"""Tests for migration 90512b932112, which drops the knowledge graph tables,
the trigger on `document`, and the KnowledgeGraphTool row."""

from collections.abc import Generator

import pytest
from sqlalchemy import Engine, create_engine, text

from onyx.configs.app_configs import (
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
)
from onyx.db.engine.sql_engine import SYNC_DB_API, build_connection_string
from tests.integration.common_utils.reset import downgrade_postgres, upgrade_postgres

PREVIOUS_REVISION = "b3e7c1d9a4f2"
DROP_REVISION = "90512b932112"
KG_TABLES = {
    "kg_entity_type",
    "kg_relationship_type",
    "kg_relationship_type_extraction_staging",
    "kg_entity",
    "kg_entity_extraction_staging",
    "kg_relationship",
    "kg_relationship_extraction_staging",
    "kg_term",
}
DOCUMENT_TRIGGER = "update_kg_entity_name_from_doc_trigger"
TOOL_ID = "KnowledgeGraphTool"


def _engine() -> Engine:
    return create_engine(
        build_connection_string(
            db="postgres",
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            db_api=SYNC_DB_API,
        )
    )


def _current_revision(engine: Engine) -> str:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()


def _kg_tables(engine: Engine) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name LIKE 'kg\\_%'"
            )
        )
        return {row[0] for row in rows}


def _document_triggers(engine: Engine) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT tgname FROM pg_trigger "
                "WHERE tgrelid = 'public.document'::regclass AND NOT tgisinternal"
            )
        )
        return {row[0] for row in rows}


def _tool_count(engine: Engine) -> int:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT count(*) FROM tool WHERE in_code_tool_id = :id"),
            {"id": TOOL_ID},
        ).scalar_one()


def _insert_document(engine: Engine, doc_id: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO document (id, semantic_id, boost, hidden, "
                "from_ingestion_api) VALUES (:id, :id, 0, false, false)"
            ),
            {"id": doc_id},
        )


@pytest.fixture(scope="module")
def engine() -> Generator[Engine, None, None]:
    downgrade_postgres(
        database="postgres", config_name="alembic", revision="base", clear_data=True
    )
    upgrade_postgres(
        database="postgres", config_name="alembic", revision=PREVIOUS_REVISION
    )
    engine = _engine()
    try:
        yield engine
    finally:
        engine.dispose()
        upgrade_postgres(database="postgres", config_name="alembic", revision="head")


@pytest.fixture
def at_previous_revision(engine: Engine) -> Engine:
    if _current_revision(engine) == DROP_REVISION:
        downgrade_postgres(
            database="postgres", config_name="alembic", revision=PREVIOUS_REVISION
        )
    assert _current_revision(engine) == PREVIOUS_REVISION
    return engine


def test_upgrade_drops_the_knowledge_graph(at_previous_revision: Engine) -> None:
    engine = at_previous_revision
    assert _kg_tables(engine) == KG_TABLES
    assert DOCUMENT_TRIGGER in _document_triggers(engine)
    assert _tool_count(engine) == 1
    _insert_document(engine, "drop-kg-doc")

    upgrade_postgres(database="postgres", config_name="alembic", revision=DROP_REVISION)

    assert _kg_tables(engine) == set()
    assert DOCUMENT_TRIGGER not in _document_triggers(engine)
    assert _tool_count(engine) == 0
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE document SET semantic_id = 'renamed' WHERE id = :id"),
            {"id": "drop-kg-doc"},
        )
        remaining = conn.execute(
            text("SELECT count(*) FROM document WHERE id = 'drop-kg-doc'")
        ).scalar_one()
    assert remaining == 1


def test_downgrade_recreates_the_tables(at_previous_revision: Engine) -> None:
    engine = at_previous_revision
    upgrade_postgres(database="postgres", config_name="alembic", revision=DROP_REVISION)
    assert _kg_tables(engine) == set()

    downgrade_postgres(
        database="postgres", config_name="alembic", revision=PREVIOUS_REVISION
    )

    assert _kg_tables(engine) == KG_TABLES
    assert DOCUMENT_TRIGGER in _document_triggers(engine)
