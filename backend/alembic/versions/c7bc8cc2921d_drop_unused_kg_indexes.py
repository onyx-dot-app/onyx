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

``upgrade()`` is idempotent — each ``DROP INDEX`` uses ``IF EXISTS``.

``downgrade()`` is intentionally a no-op. If KG is reactivated, the
needed indexes should be reintroduced via a forward migration tailored
to the new workload rather than blindly restored.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "c7bc8cc2921d"
down_revision = "b02d7b35e48b"
branch_labels = None
depends_on = None


# Alembic runs per-tenant via SET search_path in env.py, so unqualified
# index names below resolve to the current tenant's schema.
INDEXES_TO_DROP = [
    "idx_kg_entity_clustering_trigrams",
    "idx_kg_entity_normalization_trigrams",
    "ix_chunk_stats_id",
    "ix_entity_extraction_staging_acl",
    "ix_entity_extraction_staging_name_search",
    "ix_entity_name_search",
    "ix_entity_type_acl",
    "ix_kg_entity_document_id",
    "ix_kg_entity_entity_key",
    "ix_kg_entity_entity_type_id_name",
    "ix_kg_entity_extraction_staging_document_id",
    "ix_kg_entity_extraction_staging_entity_key",
    "ix_kg_entity_extraction_staging_entity_type_id_name",
    "ix_kg_entity_extraction_staging_id_name",
    "ix_kg_entity_extraction_staging_name",
    "ix_kg_entity_extraction_staging_parent_key",
    "ix_kg_entity_id_name",
    "ix_kg_entity_name",
    "ix_kg_entity_parent_key",
    "ix_kg_entity_type_id_name",
    "ix_kg_relationship_extraction_staging_id_name",
    "ix_kg_relationship_extraction_staging_nodes",
    "ix_kg_relationship_extraction_staging_relationship_type_id_name",
    "ix_kg_relationship_extraction_staging_source_document",
    "ix_kg_relationship_extraction_staging_source_node",
    "ix_kg_relationship_extraction_staging_source_node_type",
    "ix_kg_relationship_extraction_staging_target_node",
    "ix_kg_relationship_extraction_staging_target_node_type",
    "ix_kg_relationship_extraction_staging_type",
    "ix_kg_relationship_id_name",
    "ix_kg_relationship_nodes",
    "ix_kg_relationship_relationship_type_id_name",
    "ix_kg_relationship_source_document",
    "ix_kg_relationship_source_node",
    "ix_kg_relationship_source_node_type",
    "ix_kg_relationship_target_node",
    "ix_kg_relationship_target_node_type",
    "ix_kg_relationship_type",
    "ix_kg_relationship_type_extraction_staging_id_name",
    "ix_kg_relationship_type_extraction_staging_name",
    "ix_kg_relationship_type_extraction_staging_source_entit_11ac",
    "ix_kg_relationship_type_extraction_staging_target_entit_6684",
    "ix_kg_relationship_type_extraction_staging_type",
    "ix_kg_relationship_type_id_name",
    "ix_kg_relationship_type_name",
    "ix_kg_relationship_type_source_entity_type_id_name",
    "ix_kg_relationship_type_target_entity_type_id_name",
    "ix_kg_relationship_type_type",
    "ix_kg_term_id_term",
    "ix_search_term_entities",
    "ix_search_term_term",
]


def upgrade() -> None:
    for index_name in INDEXES_TO_DROP:
        op.execute(f"DROP INDEX IF EXISTS {index_name};")


def downgrade() -> None:
    pass
