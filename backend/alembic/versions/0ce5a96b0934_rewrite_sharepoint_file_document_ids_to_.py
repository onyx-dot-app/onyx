"""rewrite sharepoint file document ids to unique id guids

Revision ID: 0ce5a96b0934
Revises: bd38e2a494ff
Create Date: 2026-07-16 15:53:15.508936

SharePoint files used to be indexed under Graph drive-item ids
("01" + base32(4-byte drive hash + item unique-ID GUID)), which change when a
file moves between document libraries. The connector now mints the durable
unique-ID GUID instead. The old id embeds the new id, so this data migration
rewrites existing rows with no API calls:

- Postgres: document.id plus every referencing table, batched, in the
  migration transaction. Rows whose GUID id already exists (the deployment
  re-indexed between the code flip and this migration) are merged into the
  GUID row instead of copied.
- OpenSearch: chunk _ids embed the document id, so chunks are copied to their
  new ids (vectors preserved — no re-embedding) and the old ones deleted, in
  every active index (PRESENT and, mid-reindex, FUTURE). Copies are
  create-only so a freshly indexed GUID chunk is never overwritten by its
  stale legacy copy.

Deployments whose retrieval index is still Vespa are skipped: rewriting
Postgres without re-keying the retrieval index would break doc-id joins.
There, the connector's new ids migrate the corpus by churn instead
(re-index + prune), which the pruning / perm-sync transition guards make
safe. Re-running this migration is a no-op once no legacy ids remain.

kg_entity/kg_relationship id_name values that textually embed a document id
are left as-is; only their document-id columns are rewritten.
"""

from collections.abc import Iterator
from typing import cast
from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.orm import Session

from onyx.configs.app_configs import DISABLE_VECTOR_DB
from onyx.connectors.sharepoint.url_utils import sharepoint_guid_from_drive_item_id
from onyx.utils.logger import setup_logger

if TYPE_CHECKING:
    from onyx.db.models import SearchSettings

# revision identifiers, used by Alembic.
revision = "0ce5a96b0934"
down_revision = "bd38e2a494ff"
branch_labels = None
depends_on = None

logger = setup_logger()

_BATCH_SIZE = 250

# Referencing tables rewritten with the dedup-then-update pattern: when the
# GUID id already has a sibling row (merge case), the legacy row is dropped;
# otherwise it is repointed. sibling_key_columns are the non-doc-id columns of
# the uniqueness scope (PK or unique constraint) the doc-id column belongs to.
_CHILD_TABLES_WITH_UNIQUENESS: list[tuple[str, str, list[str]]] = [
    ("document__tag", "document_id", ["tag_id"]),
    ("persona__document", "document_id", ["persona_id"]),
    ("document_by_connector_credential_pair", "id", ["connector_id", "credential_id"]),
    ("kg_relationship", "source_document", ["id_name"]),
    ("kg_relationship_extraction_staging", "source_document", ["id_name"]),
    ("opensearch_document_migration_record", "document_id", []),
    (
        "targeted_reindex_job_target",
        "document_id",
        ["targeted_reindex_job_id", "cc_pair_id"],
    ),
]

# Referencing tables with no uniqueness constraint on the doc-id column: a
# plain repoint suffices.
_CHILD_TABLES_PLAIN: list[tuple[str, str]] = [
    ("hierarchy_node", "document_id"),
    ("document_retrieval_feedback", "document_id"),
    ("index_attempt_errors", "document_id"),
    ("search_doc", "document_id"),
    ("kg_entity", "document_id"),
    ("kg_entity_extraction_staging", "document_id"),
]


def _collect_id_mapping(bind: sa.Connection) -> dict[str, str]:
    """old drive-item id -> new lowercase GUID id, for every document attached
    to a SharePoint connector whose id decodes as a drive-item id."""
    rows = bind.execute(
        sa.text(
            """
            SELECT DISTINCT d.id
            FROM document d
            JOIN document_by_connector_credential_pair dcc ON dcc.id = d.id
            JOIN connector c ON c.id = dcc.connector_id
            WHERE c.source = 'SHAREPOINT'
            """
        )
    ).scalars()
    mapping: dict[str, str] = {}
    for old_id in rows:
        guid = sharepoint_guid_from_drive_item_id(old_id)
        if guid is not None:
            mapping[old_id] = guid
    return mapping


def _batches(items: list[tuple[str, str]]) -> Iterator[list[tuple[str, str]]]:
    for start in range(0, len(items), _BATCH_SIZE):
        yield items[start : start + _BATCH_SIZE]


def _rekey_opensearch_chunks(
    batch: list[tuple[str, str]], search_settings_list: list["SearchSettings"]
) -> None:
    """Copies each legacy doc's chunks to its GUID id (vectors preserved) and
    deletes the legacy chunks, in every active OpenSearch index."""
    # Imported lazily so Vespa-retrieval / vector-db-less upgrades never load
    # the OpenSearch stack.
    from onyx.document_index.factory import build_opensearch_document_index
    from onyx.document_index.opensearch.client import OpenSearchIndexClient
    from onyx.document_index.opensearch.schema import DocumentChunk

    mapping = dict(batch)
    old_ids = list(mapping.keys())
    for search_settings in search_settings_list:
        index = build_opensearch_document_index(search_settings)
        client = OpenSearchIndexClient(index_name=search_settings.index_name)
        for page in client.iter_chunks_for_doc_ids(old_ids, include_vectors=True):
            rekeyed = [
                chunk.model_copy(update={"document_id": mapping[chunk.document_id]})
                for chunk in cast(list[DocumentChunk], page)
            ]
            index.index_raw_chunks(rekeyed, use_create_only=True)
        for old_id in old_ids:
            index.delete(old_id)


def _rewrite_postgres_rows(bind: sa.Connection, batch: list[tuple[str, str]]) -> None:
    bind.execute(
        sa.text(
            "CREATE TEMP TABLE IF NOT EXISTS sp_doc_id_map (old_id text PRIMARY KEY, new_id text NOT NULL)"
        )
    )
    bind.execute(sa.text("DELETE FROM sp_doc_id_map"))
    bind.execute(
        sa.text("INSERT INTO sp_doc_id_map (old_id, new_id) VALUES (:old_id, :new_id)"),
        [{"old_id": old, "new_id": new} for old, new in batch],
    )

    # Copy each document row to its GUID id first so child FKs have a target;
    # merge case (GUID row already indexed) skips the copy.
    document_columns = [
        row[0]
        for row in bind.execute(
            sa.text(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = current_schema() AND table_name = 'document'
                ORDER BY ordinal_position
                """
            )
        )
    ]
    other_columns = ", ".join(f'"{c}"' for c in document_columns if c != "id")
    bind.execute(
        sa.text(
            f"""
            INSERT INTO document (id, {other_columns})
            SELECT m.new_id, {", ".join(f'd."{c}"' for c in document_columns if c != "id")}
            FROM document d
            JOIN sp_doc_id_map m ON d.id = m.old_id
            WHERE NOT EXISTS (SELECT 1 FROM document d2 WHERE d2.id = m.new_id)
            """
        )
    )

    for table, doc_column, sibling_keys in _CHILD_TABLES_WITH_UNIQUENESS:
        sibling_match = " AND ".join(f't2."{key}" = t."{key}"' for key in sibling_keys)
        exists_clause = f't2."{doc_column}" = m.new_id' + (
            f" AND {sibling_match}" if sibling_match else ""
        )
        bind.execute(
            sa.text(
                f"""
                DELETE FROM {table} t
                USING sp_doc_id_map m
                WHERE t."{doc_column}" = m.old_id
                  AND EXISTS (SELECT 1 FROM {table} t2 WHERE {exists_clause})
                """
            )
        )
        bind.execute(
            sa.text(
                f"""
                UPDATE {table} t SET "{doc_column}" = m.new_id
                FROM sp_doc_id_map m WHERE t."{doc_column}" = m.old_id
                """
            )
        )

    # chunk_stats additionally derives its PK from the doc id
    # (f"{document_id}__{chunk_in_doc_id}"), so both columns are rewritten.
    bind.execute(
        sa.text(
            """
            DELETE FROM chunk_stats t
            USING sp_doc_id_map m
            WHERE t.document_id = m.old_id
              AND EXISTS (
                SELECT 1 FROM chunk_stats t2
                WHERE t2.document_id = m.new_id
                  AND t2.chunk_in_doc_id = t.chunk_in_doc_id
              )
            """
        )
    )
    bind.execute(
        sa.text(
            """
            UPDATE chunk_stats t
            SET document_id = m.new_id,
                id = m.new_id || substring(t.id FROM char_length(m.old_id) + 1)
            FROM sp_doc_id_map m WHERE t.document_id = m.old_id
            """
        )
    )

    for table, doc_column in _CHILD_TABLES_PLAIN:
        bind.execute(
            sa.text(
                f"""
                UPDATE {table} t SET "{doc_column}" = m.new_id
                FROM sp_doc_id_map m WHERE t."{doc_column}" = m.old_id
                """
            )
        )

    bind.execute(
        sa.text("DELETE FROM document d USING sp_doc_id_map m WHERE d.id = m.old_id")
    )


def upgrade() -> None:
    bind = op.get_bind()

    mapping = _collect_id_mapping(bind)
    if not mapping:
        return

    search_settings_list: list["SearchSettings"] = []
    if not DISABLE_VECTOR_DB:
        from onyx.db.opensearch_migration import get_opensearch_retrieval_state
        from onyx.db.search_settings import get_current_search_settings
        from onyx.db.search_settings import get_secondary_search_settings

        with Session(bind=bind) as db_session:
            if not get_opensearch_retrieval_state(db_session):
                logger.warning(
                    "Skipping SharePoint document-id rewrite for %s legacy docs: "
                    "retrieval is not on OpenSearch, so chunks cannot be re-keyed "
                    "in place. The corpus migrates by churn (re-index + prune) "
                    "instead.",
                    len(mapping),
                )
                return
            search_settings_list.append(get_current_search_settings(db_session))
            secondary = get_secondary_search_settings(db_session)
            if secondary is not None:
                search_settings_list.append(secondary)

    logger.info(
        "Rewriting %s SharePoint documents from drive-item ids to unique-ID GUIDs",
        len(mapping),
    )
    for batch in _batches(sorted(mapping.items())):
        if search_settings_list:
            # Chunk copies land before the Postgres rows flip so retrieval by
            # the new ids works the moment the transaction commits; copies are
            # create-only, so a rerun after a mid-migration crash is safe.
            _rekey_opensearch_chunks(batch, search_settings_list)
        _rewrite_postgres_rows(bind, batch)

    bind.execute(sa.text("DROP TABLE IF EXISTS sp_doc_id_map"))


def downgrade() -> None:
    # Irreversible data migration: the drive hash inside the legacy id is not
    # recoverable from the GUID without Graph calls. Rolling back the code is
    # safe without downgrading — old connector code would re-index GUID docs
    # as new, which the transition guards already handle.
    pass
