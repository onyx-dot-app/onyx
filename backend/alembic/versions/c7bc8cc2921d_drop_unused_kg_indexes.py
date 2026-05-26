"""drop_unused_kg_indexes

Revision ID: c7bc8cc2921d
Revises: b02d7b35e48b
Create Date: 2026-05-26 13:00:00.000000

Drop a set of unused database indexes from each tenant schema.

Motivation
----------
The ``managed_services`` cluster's primary RDS instance hit the EXT4
htree directory limit on its data volume because the multi-tenant
deployment (>6,000 tenant schemas) creates the same set of indexes per
schema, multiplying every redundant index by the tenant count. The
Knowledge Graph (KG) feature is not in active use on
``managed_services``: across 6,134 tenants we observed zero index
scans on the KG indexes (``pg_stat_user_indexes.idx_scan = 0``) over a
3+ day observation window. We are dropping their non-PK, non-unique
indexes here.

Also included: ``ix_chunk_stats_id``, a redundant b-tree on
``chunk_stats.id`` that duplicates the primary key index.

Out of scope: the underlying ``kg_*`` tables and their unique
constraints (``uq_kg_*``) remain — only secondary indexes are dropped.
If KG is re-enabled later, the corresponding ``CREATE INDEX``
statements will need to be reintroduced via a follow-up migration.

Manual cleanup already performed
--------------------------------
The DB-side ``DROP INDEX`` was run manually across all existing tenant
schemas on 2026-05-26, before this migration shipped. This migration's
job is to:

  (a) catch any new tenants that received these indexes during
      provisioning windows that overlapped the manual cleanup, and
  (b) keep schema state matching the model definitions in this PR (so
      that ``alembic upgrade head`` on a fresh tenant doesn't leave
      orphan indexes that don't exist in ``models.py``).

``IF EXISTS`` makes each DROP idempotent.

Downgrade
---------
``downgrade()`` is intentionally a no-op. These indexes were determined
to be unused and we don't want to restore them on rollback. If KG
re-enablement is required, write a forward migration that recreates
only the indexes that are actually needed for the new workload.
"""

from alembic import op
import sqlalchemy as sa  # noqa: F401  (kept for alembic template consistency)


# revision identifiers, used by Alembic.
revision = "c7bc8cc2921d"
down_revision = "b02d7b35e48b"
branch_labels = None
depends_on = None


# 51 indexes dropped per tenant schema. Alembic runs with
# schema_translate_map, so the unqualified index names below resolve to
# the current tenant's schema for each invocation.
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
    # Intentional no-op. These indexes were determined unused (zero
    # index scans across thousands of tenants over multiple days) and
    # we do not restore them on rollback. If KG is re-enabled, write a
    # forward migration that recreates only the indexes that the new
    # workload actually needs.
    pass
