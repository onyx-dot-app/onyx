"""remove_knowledge_graph

Revision ID: 6a2cb6cf898d
Revises: 4e9bb4eabe26
Create Date: 2026-05-25 18:52:37.404822

Removes the structured Knowledge Graph feature end-to-end:
- the two trigger/function pairs that maintained kg_entity.name
- 9 KG tables (kg_term, kg_relationship, kg_entity, kg_relationship_type,
  *_extraction_staging variants, kg_entity_type, kg_config)
- 4 KG columns on document/connector
- the kg_config key from key_value_store
- the seeded KnowledgeGraphTool row in `tool`

The pg_trgm extension is left installed — it's used outside KG.

Operators should run the pre-flight count query documented in the phase-7
plan (kg_connectors / active_entity_types / entities / relationships)
BEFORE merging this migration; it's the meaningful go/no-go gate.

Forward-only migration. downgrade() raises NotImplementedError; restore
from backup if recovery is needed.
"""

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "6a2cb6cf898d"
down_revision = "4e9bb4eabe26"
branch_labels = None
depends_on = None


# Reflected light-weight table handles used for DML below. Declared at module
# scope so they're available without re-declaration inside upgrade().
_KEY_VALUE_STORE = sa.table(
    "key_value_store",
    sa.column("key", sa.String()),
)
_TOOL = sa.table(
    "tool",
    sa.column("in_code_tool_id", sa.String()),
)


def upgrade() -> None:
    # -----------------------------------------------------------------
    # 1. Drop triggers + their functions. Names use the *_trigger suffix
    #    per the creation migration; function name is the bare label.
    #
    #    PostgreSQL-specific. No Alembic native API for triggers/funcs.
    # -----------------------------------------------------------------
    for table, function in (
        ("kg_entity", "update_kg_entity_name"),
        ("document", "update_kg_entity_name_from_doc"),
    ):
        op.execute(sa.text(f"DROP TRIGGER IF EXISTS {function}_trigger ON {table}"))
        op.execute(sa.text(f"DROP FUNCTION IF EXISTS {function}() CASCADE"))

    # -----------------------------------------------------------------
    # 2. Drop KG tables in FK-safe order (reverse of creation).
    #
    #    NOTE: if an install has leaked per-user temp views referencing
    #    these tables (named with prefixes `kg_relationships_with_access_*`,
    #    `kg_entities_with_access_*`, `allowed_docs_*`), the drop will
    #    fail. KG has been dormant for months and is off for most
    #    customers, so this is unlikely. If it surfaces, the operator
    #    drops the offending views manually and reruns.
    # -----------------------------------------------------------------
    for table_name in (
        "kg_term",
        "kg_relationship",
        "kg_entity",
        "kg_relationship_type",
        "kg_relationship_extraction_staging",
        "kg_relationship_type_extraction_staging",
        "kg_entity_extraction_staging",
        "kg_entity_type",
        "kg_config",
    ):
        op.drop_table(table_name)

    # -----------------------------------------------------------------
    # 3. Drop KG columns from non-KG tables.
    # -----------------------------------------------------------------
    op.drop_column("connector", "kg_processing_enabled")
    op.drop_column("connector", "kg_coverage_days")
    op.drop_column("document", "kg_stage")
    op.drop_column("document", "kg_processing_time")

    # -----------------------------------------------------------------
    # 4. Drop the KV-store entry for kg_config (separate from the
    #    kg_config table dropped above; this is the KV-shaped config the
    #    runtime code wrote via key_value_store).
    # -----------------------------------------------------------------
    op.execute(sa.delete(_KEY_VALUE_STORE).where(_KEY_VALUE_STORE.c.key == "kg_config"))

    # -----------------------------------------------------------------
    # 5. Delete the seeded KnowledgeGraphTool row in `tool`. The Python
    #    class backing it is removed, so the row would dangle. Any
    #    persona_tool rows that referenced it cascade via FK.
    # -----------------------------------------------------------------
    op.execute(sa.delete(_TOOL).where(_TOOL.c.in_code_tool_id == "KnowledgeGraphTool"))


def downgrade() -> None:
    raise NotImplementedError(
        "Forward-only migration; restore from backup to recover KG schema."
    )
