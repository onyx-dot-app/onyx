"""drop_unused_kg_indexes

Revision ID: c7bc8cc2921d
Revises: b02d7b35e48b
Create Date: 2026-05-26 13:00:00.000000

Drop unused secondary indexes from KG tables and the redundant index
on ``chunk_stats.id`` (already covered by its primary key).

These secondary indexes have no observed usage and are not used by
current queries. Dropping them reduces per-tenant schema size and
catalog overhead in multi-tenant deployments.

Out of scope: the ``kg_*`` tables themselves, their primary keys, and
their unique constraints (``uq_*``) are unchanged.

``upgrade()`` and ``downgrade()`` are both idempotent (``IF EXISTS`` on
drop, ``IF NOT EXISTS`` on create). The two paths share a single source
of truth (``INDEXES``) so they stay in sync.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c7bc8cc2921d"
down_revision = "b02d7b35e48b"
branch_labels = None
depends_on = None


# (index_name, CREATE INDEX statement) for each index this migration
# manages. Alembic runs per-tenant via SET search_path in env.py, so
# unqualified names below resolve to the current tenant's schema.
INDEXES: list[tuple[str, str]] = [
    (
        "idx_kg_entity_clustering_trigrams",
        "CREATE INDEX IF NOT EXISTS idx_kg_entity_clustering_trigrams "
        "ON kg_entity USING gin (name public.gin_trgm_ops)",
    ),
    (
        "idx_kg_entity_normalization_trigrams",
        "CREATE INDEX IF NOT EXISTS idx_kg_entity_normalization_trigrams "
        "ON kg_entity USING gin (name_trigrams)",
    ),
    (
        "ix_chunk_stats_id",
        "CREATE INDEX IF NOT EXISTS ix_chunk_stats_id ON chunk_stats USING btree (id)",
    ),
    (
        "ix_entity_extraction_staging_acl",
        "CREATE INDEX IF NOT EXISTS ix_entity_extraction_staging_acl "
        "ON kg_entity_extraction_staging USING btree (entity_type_id_name, acl)",
    ),
    (
        "ix_entity_extraction_staging_name_search",
        "CREATE INDEX IF NOT EXISTS ix_entity_extraction_staging_name_search "
        "ON kg_entity_extraction_staging USING btree (name, entity_type_id_name)",
    ),
    (
        "ix_entity_name_search",
        "CREATE INDEX IF NOT EXISTS ix_entity_name_search "
        "ON kg_entity USING btree (name, entity_type_id_name)",
    ),
    (
        "ix_entity_type_acl",
        "CREATE INDEX IF NOT EXISTS ix_entity_type_acl "
        "ON kg_entity USING btree (entity_type_id_name, acl)",
    ),
    (
        "ix_kg_entity_document_id",
        "CREATE INDEX IF NOT EXISTS ix_kg_entity_document_id "
        "ON kg_entity USING btree (document_id)",
    ),
    (
        "ix_kg_entity_entity_key",
        "CREATE INDEX IF NOT EXISTS ix_kg_entity_entity_key "
        "ON kg_entity USING btree (entity_key)",
    ),
    (
        "ix_kg_entity_entity_type_id_name",
        "CREATE INDEX IF NOT EXISTS ix_kg_entity_entity_type_id_name "
        "ON kg_entity USING btree (entity_type_id_name)",
    ),
    (
        "ix_kg_entity_extraction_staging_document_id",
        "CREATE INDEX IF NOT EXISTS ix_kg_entity_extraction_staging_document_id "
        "ON kg_entity_extraction_staging USING btree (document_id)",
    ),
    (
        "ix_kg_entity_extraction_staging_entity_key",
        "CREATE INDEX IF NOT EXISTS ix_kg_entity_extraction_staging_entity_key "
        "ON kg_entity_extraction_staging USING btree (entity_key)",
    ),
    (
        "ix_kg_entity_extraction_staging_entity_type_id_name",
        "CREATE INDEX IF NOT EXISTS ix_kg_entity_extraction_staging_entity_type_id_name "
        "ON kg_entity_extraction_staging USING btree (entity_type_id_name)",
    ),
    (
        "ix_kg_entity_extraction_staging_id_name",
        "CREATE INDEX IF NOT EXISTS ix_kg_entity_extraction_staging_id_name "
        "ON kg_entity_extraction_staging USING btree (id_name)",
    ),
    (
        "ix_kg_entity_extraction_staging_name",
        "CREATE INDEX IF NOT EXISTS ix_kg_entity_extraction_staging_name "
        "ON kg_entity_extraction_staging USING btree (name)",
    ),
    (
        "ix_kg_entity_extraction_staging_parent_key",
        "CREATE INDEX IF NOT EXISTS ix_kg_entity_extraction_staging_parent_key "
        "ON kg_entity_extraction_staging USING btree (parent_key)",
    ),
    (
        "ix_kg_entity_id_name",
        "CREATE INDEX IF NOT EXISTS ix_kg_entity_id_name "
        "ON kg_entity USING btree (id_name)",
    ),
    (
        "ix_kg_entity_name",
        "CREATE INDEX IF NOT EXISTS ix_kg_entity_name ON kg_entity USING btree (name)",
    ),
    (
        "ix_kg_entity_parent_key",
        "CREATE INDEX IF NOT EXISTS ix_kg_entity_parent_key "
        "ON kg_entity USING btree (parent_key)",
    ),
    (
        "ix_kg_entity_type_id_name",
        "CREATE INDEX IF NOT EXISTS ix_kg_entity_type_id_name "
        "ON kg_entity_type USING btree (id_name)",
    ),
    (
        "ix_kg_relationship_extraction_staging_id_name",
        "CREATE INDEX IF NOT EXISTS ix_kg_relationship_extraction_staging_id_name "
        "ON kg_relationship_extraction_staging USING btree (id_name)",
    ),
    (
        "ix_kg_relationship_extraction_staging_nodes",
        "CREATE INDEX IF NOT EXISTS ix_kg_relationship_extraction_staging_nodes "
        "ON kg_relationship_extraction_staging USING btree (source_node, target_node)",
    ),
    (
        "ix_kg_relationship_extraction_staging_relationship_type_id_name",
        "CREATE INDEX IF NOT EXISTS "
        "ix_kg_relationship_extraction_staging_relationship_type_id_name "
        "ON kg_relationship_extraction_staging USING btree (relationship_type_id_name)",
    ),
    (
        "ix_kg_relationship_extraction_staging_source_document",
        "CREATE INDEX IF NOT EXISTS ix_kg_relationship_extraction_staging_source_document "
        "ON kg_relationship_extraction_staging USING btree (source_document)",
    ),
    (
        "ix_kg_relationship_extraction_staging_source_node",
        "CREATE INDEX IF NOT EXISTS ix_kg_relationship_extraction_staging_source_node "
        "ON kg_relationship_extraction_staging USING btree (source_node)",
    ),
    (
        "ix_kg_relationship_extraction_staging_source_node_type",
        "CREATE INDEX IF NOT EXISTS ix_kg_relationship_extraction_staging_source_node_type "
        "ON kg_relationship_extraction_staging USING btree (source_node_type)",
    ),
    (
        "ix_kg_relationship_extraction_staging_target_node",
        "CREATE INDEX IF NOT EXISTS ix_kg_relationship_extraction_staging_target_node "
        "ON kg_relationship_extraction_staging USING btree (target_node)",
    ),
    (
        "ix_kg_relationship_extraction_staging_target_node_type",
        "CREATE INDEX IF NOT EXISTS ix_kg_relationship_extraction_staging_target_node_type "
        "ON kg_relationship_extraction_staging USING btree (target_node_type)",
    ),
    (
        "ix_kg_relationship_extraction_staging_type",
        "CREATE INDEX IF NOT EXISTS ix_kg_relationship_extraction_staging_type "
        "ON kg_relationship_extraction_staging USING btree (type)",
    ),
    (
        "ix_kg_relationship_id_name",
        "CREATE INDEX IF NOT EXISTS ix_kg_relationship_id_name "
        "ON kg_relationship USING btree (id_name)",
    ),
    (
        "ix_kg_relationship_nodes",
        "CREATE INDEX IF NOT EXISTS ix_kg_relationship_nodes "
        "ON kg_relationship USING btree (source_node, target_node)",
    ),
    (
        "ix_kg_relationship_relationship_type_id_name",
        "CREATE INDEX IF NOT EXISTS ix_kg_relationship_relationship_type_id_name "
        "ON kg_relationship USING btree (relationship_type_id_name)",
    ),
    (
        "ix_kg_relationship_source_document",
        "CREATE INDEX IF NOT EXISTS ix_kg_relationship_source_document "
        "ON kg_relationship USING btree (source_document)",
    ),
    (
        "ix_kg_relationship_source_node",
        "CREATE INDEX IF NOT EXISTS ix_kg_relationship_source_node "
        "ON kg_relationship USING btree (source_node)",
    ),
    (
        "ix_kg_relationship_source_node_type",
        "CREATE INDEX IF NOT EXISTS ix_kg_relationship_source_node_type "
        "ON kg_relationship USING btree (source_node_type)",
    ),
    (
        "ix_kg_relationship_target_node",
        "CREATE INDEX IF NOT EXISTS ix_kg_relationship_target_node "
        "ON kg_relationship USING btree (target_node)",
    ),
    (
        "ix_kg_relationship_target_node_type",
        "CREATE INDEX IF NOT EXISTS ix_kg_relationship_target_node_type "
        "ON kg_relationship USING btree (target_node_type)",
    ),
    (
        "ix_kg_relationship_type",
        "CREATE INDEX IF NOT EXISTS ix_kg_relationship_type "
        "ON kg_relationship USING btree (type)",
    ),
    (
        "ix_kg_relationship_type_extraction_staging_id_name",
        "CREATE INDEX IF NOT EXISTS ix_kg_relationship_type_extraction_staging_id_name "
        "ON kg_relationship_type_extraction_staging USING btree (id_name)",
    ),
    (
        "ix_kg_relationship_type_extraction_staging_name",
        "CREATE INDEX IF NOT EXISTS ix_kg_relationship_type_extraction_staging_name "
        "ON kg_relationship_type_extraction_staging USING btree (name)",
    ),
    (
        "ix_kg_relationship_type_extraction_staging_source_entit_11ac",
        "CREATE INDEX IF NOT EXISTS "
        "ix_kg_relationship_type_extraction_staging_source_entit_11ac "
        "ON kg_relationship_type_extraction_staging USING btree (source_entity_type_id_name)",
    ),
    (
        "ix_kg_relationship_type_extraction_staging_target_entit_6684",
        "CREATE INDEX IF NOT EXISTS "
        "ix_kg_relationship_type_extraction_staging_target_entit_6684 "
        "ON kg_relationship_type_extraction_staging USING btree (target_entity_type_id_name)",
    ),
    (
        "ix_kg_relationship_type_extraction_staging_type",
        "CREATE INDEX IF NOT EXISTS ix_kg_relationship_type_extraction_staging_type "
        "ON kg_relationship_type_extraction_staging USING btree (type)",
    ),
    (
        "ix_kg_relationship_type_id_name",
        "CREATE INDEX IF NOT EXISTS ix_kg_relationship_type_id_name "
        "ON kg_relationship_type USING btree (id_name)",
    ),
    (
        "ix_kg_relationship_type_name",
        "CREATE INDEX IF NOT EXISTS ix_kg_relationship_type_name "
        "ON kg_relationship_type USING btree (name)",
    ),
    (
        "ix_kg_relationship_type_source_entity_type_id_name",
        "CREATE INDEX IF NOT EXISTS ix_kg_relationship_type_source_entity_type_id_name "
        "ON kg_relationship_type USING btree (source_entity_type_id_name)",
    ),
    (
        "ix_kg_relationship_type_target_entity_type_id_name",
        "CREATE INDEX IF NOT EXISTS ix_kg_relationship_type_target_entity_type_id_name "
        "ON kg_relationship_type USING btree (target_entity_type_id_name)",
    ),
    (
        "ix_kg_relationship_type_type",
        "CREATE INDEX IF NOT EXISTS ix_kg_relationship_type_type "
        "ON kg_relationship_type USING btree (type)",
    ),
    (
        "ix_kg_term_id_term",
        "CREATE INDEX IF NOT EXISTS ix_kg_term_id_term "
        "ON kg_term USING btree (id_term)",
    ),
    (
        "ix_search_term_entities",
        "CREATE INDEX IF NOT EXISTS ix_search_term_entities "
        "ON kg_term USING btree (entity_types)",
    ),
    (
        "ix_search_term_term",
        "CREATE INDEX IF NOT EXISTS ix_search_term_term "
        "ON kg_term USING btree (id_term)",
    ),
]


def upgrade() -> None:
    for name, _create_sql in INDEXES:
        op.execute(sa.text(f"DROP INDEX IF EXISTS {name};"))


def downgrade() -> None:
    for _name, create_sql in INDEXES:
        op.execute(sa.text(create_sql + ";"))
