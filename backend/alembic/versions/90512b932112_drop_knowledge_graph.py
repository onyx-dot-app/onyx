"""drop knowledge graph

The knowledge graph was removed from the product. Nothing reads or writes its
tables, triggers or tool row anymore.

The nullable `document.kg_stage`, `document.kg_processing_time`,
`connector.kg_processing_enabled` and `connector.kg_coverage_days` columns stay
for now. Old pods still map them during a rolling deploy, and a later release
drops them.

Revision ID: 90512b932112
Revises: b3e7c1d9a4f2
Create Date: 2026-10-05 09:28:05.537525

"""

import logging
import time
from collections.abc import Callable

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError

from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA

logger = logging.getLogger("alembic.runtime.migration")

# revision identifiers, used by Alembic.
revision = "90512b932112"
down_revision = "b3e7c1d9a4f2"
branch_labels = None
depends_on = None

_LOCK_TIMEOUT = "5s"
_DROP_ATTEMPTS = 12
_RETRY_DELAY_S = 5
# SQLSTATE lock_not_available: the error a lock_timeout raises.
_LOCK_NOT_AVAILABLE = "55P03"

_KV_CONFIG_KEY = "kg_config"
_TOOL_IN_CODE_ID = "KnowledgeGraphTool"

_ENTITY_NAME_FUNCTION = "update_kg_entity_name"
_DOCUMENT_NAME_FUNCTION = "update_kg_entity_name_from_doc"
_ALPHANUM_PATTERN = r"[^a-z0-9]+"
_TRUNCATE_LENGTH = 1000


def _is_lock_timeout(error: DBAPIError) -> bool:
    # psycopg2 and SQLAlchemy's asyncpg adapter both set `pgcode` on the
    # driver error, but the DBAPI error type does not declare it.
    pgcode = getattr(error.orig, "pgcode", None)  # ods: ignore[getattr]
    return pgcode == _LOCK_NOT_AVAILABLE


def _with_bounded_lock_wait(description: str, statement: Callable[[], None]) -> None:
    """Runs a statement that needs an ACCESS EXCLUSIVE lock on `document`.

    While it waits for that lock, every other query on `document` queues behind
    it. A short lock_timeout keeps that stall short when a long transaction (for
    example an indexing batch) holds a lock on `document`. Each attempt runs in a
    savepoint, so a timeout does not abort the migration transaction.
    """
    bind = op.get_bind()
    for attempt in range(1, _DROP_ATTEMPTS + 1):
        try:
            with bind.begin_nested():
                bind.execute(sa.text(f"SET LOCAL lock_timeout = '{_LOCK_TIMEOUT}'"))
                statement()
            break
        except DBAPIError as e:
            # Only a lock timeout is worth a retry. Raise other errors at once.
            if attempt == _DROP_ATTEMPTS or not _is_lock_timeout(e):
                raise
            logger.warning(
                "Could not lock `document` to %s (attempt %s/%s). Retrying in %ss.",
                description,
                attempt,
                _DROP_ATTEMPTS,
                _RETRY_DELAY_S,
            )
            time.sleep(_RETRY_DELAY_S)
    bind.execute(sa.text("SET LOCAL lock_timeout = DEFAULT"))


def _drop_table_with_bounded_lock_wait(table_name: str) -> None:
    """Drops a table whose foreign key points at `document`."""
    _with_bounded_lock_wait(f"drop {table_name}", lambda: op.drop_table(table_name))


def _drop_document_trigger() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {_DOCUMENT_NAME_FUNCTION}_trigger ON document")


def upgrade() -> None:
    _with_bounded_lock_wait("drop the document trigger", _drop_document_trigger)

    op.execute(f"DROP TRIGGER IF EXISTS {_ENTITY_NAME_FUNCTION}_trigger ON kg_entity")
    op.execute(f"DROP FUNCTION IF EXISTS {_ENTITY_NAME_FUNCTION}()")
    op.execute(f"DROP FUNCTION IF EXISTS {_DOCUMENT_NAME_FUNCTION}()")

    _drop_table_with_bounded_lock_wait("kg_relationship_extraction_staging")
    _drop_table_with_bounded_lock_wait("kg_relationship")
    _drop_table_with_bounded_lock_wait("kg_entity_extraction_staging")
    op.drop_table("kg_relationship_type_extraction_staging")
    op.drop_table("kg_relationship_type")
    _drop_table_with_bounded_lock_wait("kg_entity")
    op.drop_table("kg_term")
    op.drop_table("kg_entity_type")

    # persona__tool rows for the tool go with it (ON DELETE CASCADE).
    op.execute(
        text("DELETE FROM tool WHERE in_code_tool_id = :tool_id").bindparams(
            tool_id=_TOOL_IN_CODE_ID
        )
    )
    op.execute(
        text("DELETE FROM key_value_store WHERE key = :key").bindparams(
            key=_KV_CONFIG_KEY
        )
    )


def _time_columns(with_updated: bool) -> list[sa.Column]:
    columns = []
    if with_updated:
        columns.append(
            sa.Column(
                "time_updated",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            )
        )
    columns.append(
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        )
    )
    return columns


def _create_relationship_type_table(table_name: str, staging: bool) -> None:
    columns = [
        sa.Column("id_name", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("source_entity_type_id_name", sa.String(), nullable=False),
        sa.Column("target_entity_type_id_name", sa.String(), nullable=False),
        sa.Column("definition", sa.Boolean(), nullable=False),
        sa.Column(
            "clustering",
            postgresql.JSONB(),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("occurrences", sa.Integer(), nullable=False),
    ]
    if staging:
        columns.append(sa.Column("transferred", sa.Boolean(), nullable=False))
    op.create_table(
        table_name,
        *columns,
        *_time_columns(with_updated=not staging),
        sa.PrimaryKeyConstraint("id_name"),
        sa.ForeignKeyConstraint(
            ["source_entity_type_id_name"], ["kg_entity_type.id_name"]
        ),
        sa.ForeignKeyConstraint(
            ["target_entity_type_id_name"], ["kg_entity_type.id_name"]
        ),
    )


def _create_entity_table(table_name: str, document_fk_name: str, staging: bool) -> None:
    columns = [
        sa.Column("id_name", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "attributes",
            postgresql.JSONB(),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("document_id", sa.String(), nullable=True),
        sa.Column("alternative_names", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("entity_type_id_name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("keywords", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("occurrences", sa.Integer(), nullable=False),
        sa.Column("acl", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("boosts", postgresql.JSONB(), nullable=False),
        sa.Column("entity_key", sa.String(), nullable=True),
        sa.Column("parent_key", sa.String(), nullable=True),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=True),
    ]
    if staging:
        columns.append(sa.Column("transferred_id_name", sa.String(), nullable=True))
    else:
        columns.append(
            sa.Column(
                "name_trigrams", postgresql.ARRAY(sa.String(length=3)), nullable=True
            )
        )
    op.create_table(
        table_name,
        *columns,
        *_time_columns(with_updated=not staging),
        sa.PrimaryKeyConstraint("id_name"),
        sa.ForeignKeyConstraint(["entity_type_id_name"], ["kg_entity_type.id_name"]),
        sa.ForeignKeyConstraint(
            ["document_id"], ["document.id"], name=document_fk_name
        ),
    )


def _create_relationship_table(
    table_name: str,
    document_fk_name: str,
    entity_table: str,
    relationship_type_table: str,
    unique_name: str,
    staging: bool,
) -> None:
    columns = [
        sa.Column("id_name", sa.String(), nullable=False),
        sa.Column("source_document", sa.String(), nullable=False),
        sa.Column("source_node", sa.String(), nullable=False),
        sa.Column("target_node", sa.String(), nullable=False),
        sa.Column("source_node_type", sa.String(), nullable=False),
        sa.Column("target_node_type", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("relationship_type_id_name", sa.String(), nullable=False),
        sa.Column("occurrences", sa.Integer(), nullable=False),
    ]
    if staging:
        columns.append(sa.Column("transferred", sa.Boolean(), nullable=False))
    op.create_table(
        table_name,
        *columns,
        *_time_columns(with_updated=not staging),
        sa.PrimaryKeyConstraint("id_name", "source_document"),
        sa.ForeignKeyConstraint(
            ["source_document"], ["document.id"], name=document_fk_name
        ),
        sa.ForeignKeyConstraint(["source_node"], [f"{entity_table}.id_name"]),
        sa.ForeignKeyConstraint(["target_node"], [f"{entity_table}.id_name"]),
        sa.ForeignKeyConstraint(["source_node_type"], ["kg_entity_type.id_name"]),
        sa.ForeignKeyConstraint(["target_node_type"], ["kg_entity_type.id_name"]),
        sa.ForeignKeyConstraint(
            ["relationship_type_id_name"], [f"{relationship_type_table}.id_name"]
        ),
        sa.UniqueConstraint("source_node", "target_node", "type", name=unique_name),
    )


def _create_trigger_functions_and_triggers() -> None:
    tenant_id = op.get_bind().execute(text("SELECT current_schema()")).scalar_one()
    function = _ENTITY_NAME_FUNCTION
    op.execute(
        text(f"""
            CREATE OR REPLACE FUNCTION "{tenant_id}".{function}()
            RETURNS TRIGGER AS $$
            DECLARE
                name text;
                cleaned_name text;
            BEGIN
                -- Set name to semantic_id if document_id is not NULL
                IF NEW.document_id IS NOT NULL THEN
                    SELECT lower(semantic_id) INTO name
                    FROM "{tenant_id}".document
                    WHERE id = NEW.document_id;
                ELSE
                    name = lower(NEW.name);
                END IF;

                -- Clean name and truncate if too long
                cleaned_name = regexp_replace(
                    name,
                    '{_ALPHANUM_PATTERN}', '', 'g'
                );
                IF length(cleaned_name) > {_TRUNCATE_LENGTH} THEN
                    cleaned_name = left(cleaned_name, {_TRUNCATE_LENGTH});
                END IF;

                -- Set name and name trigrams
                NEW.name = name;
                NEW.name_trigrams = {POSTGRES_DEFAULT_SCHEMA}.show_trgm(cleaned_name);
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """)
    )
    trigger = f"{function}_trigger"
    op.execute(f'DROP TRIGGER IF EXISTS {trigger} ON "{tenant_id}".kg_entity')
    op.execute(f"""
        CREATE TRIGGER {trigger}
            BEFORE INSERT OR UPDATE OF name
            ON "{tenant_id}".kg_entity
            FOR EACH ROW
            EXECUTE FUNCTION "{tenant_id}".{function}();
        """)

    function = _DOCUMENT_NAME_FUNCTION
    op.execute(
        text(f"""
            CREATE OR REPLACE FUNCTION "{tenant_id}".{function}()
            RETURNS TRIGGER AS $$
            DECLARE
                doc_name text;
                cleaned_name text;
            BEGIN
                doc_name = lower(NEW.semantic_id);

                -- Clean name and truncate if too long
                cleaned_name = regexp_replace(
                    doc_name,
                    '{_ALPHANUM_PATTERN}', '', 'g'
                );
                IF length(cleaned_name) > {_TRUNCATE_LENGTH} THEN
                    cleaned_name = left(cleaned_name, {_TRUNCATE_LENGTH});
                END IF;

                -- Set name and name trigrams for all entities referencing this document
                UPDATE "{tenant_id}".kg_entity
                SET
                    name = doc_name,
                    name_trigrams = {POSTGRES_DEFAULT_SCHEMA}.show_trgm(cleaned_name)
                WHERE document_id = NEW.id;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """)
    )
    trigger = f"{function}_trigger"
    op.execute(f'DROP TRIGGER IF EXISTS {trigger} ON "{tenant_id}".document')
    op.execute(f"""
        CREATE TRIGGER {trigger}
            AFTER UPDATE OF semantic_id
            ON "{tenant_id}".document
            FOR EACH ROW
            EXECUTE FUNCTION "{tenant_id}".{function}();
        """)


def downgrade() -> None:
    # The KnowledgeGraphTool row and the kg_config row are not restored. Both
    # were seeded data, and nothing in the product reads them.
    op.create_table(
        "kg_entity_type",
        sa.Column("id_name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("grounding", sa.String(), nullable=False),
        sa.Column(
            "attributes",
            postgresql.JSONB(),
            server_default="{}",
            nullable=True,
            comment="Filtering based on document attribute",
        ),
        sa.Column("occurrences", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("deep_extraction", sa.Boolean(), nullable=False),
        sa.Column(
            "time_updated",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("grounded_source_name", sa.String(), nullable=True),
        sa.Column("entity_values", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column(
            "clustering",
            postgresql.JSONB(),
            server_default="{}",
            nullable=False,
            comment="Clustering information for this entity type",
        ),
        sa.PrimaryKeyConstraint("id_name"),
    )
    op.create_table(
        "kg_term",
        sa.Column("id_term", sa.String(), nullable=False),
        sa.Column("entity_types", postgresql.ARRAY(sa.String()), nullable=False),
        *_time_columns(with_updated=True),
        sa.PrimaryKeyConstraint("id_term"),
    )
    _create_entity_table("kg_entity", "kg_entity_document_id_fkey", staging=False)
    _create_relationship_type_table("kg_relationship_type", staging=False)
    _create_relationship_type_table(
        "kg_relationship_type_extraction_staging", staging=True
    )
    _create_entity_table(
        "kg_entity_extraction_staging",
        "kg_entity_extraction_staging_document_id_fkey",
        staging=True,
    )
    _create_relationship_table(
        "kg_relationship",
        "kg_relationship_source_document_fkey",
        "kg_entity",
        "kg_relationship_type",
        "uq_kg_relationship_source_target_type",
        staging=False,
    )
    _create_relationship_table(
        "kg_relationship_extraction_staging",
        "kg_relationship_extraction_staging_source_document_fkey",
        "kg_entity_extraction_staging",
        "kg_relationship_type_extraction_staging",
        "uq_kg_relationship_extraction_staging_source_target_type",
        staging=True,
    )
    _create_trigger_functions_and_triggers()
