"""userfile_schema_updates_project_links_and_cleanup

Revision ID: 238736219dd4
Revises: 505c488f6662
Create Date: 2025-09-16 17:32:43.151946

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as psql
from sqlalchemy import text

# External services / utils
import httpx
from onyx.document_index.factory import get_default_document_index
from onyx.db.search_settings import SearchSettings
from onyx.document_index.vespa.shared_utils.utils import get_vespa_http_client
from onyx.document_index.vespa.shared_utils.utils import (
    replace_invalid_doc_id_characters,
)
from onyx.document_index.vespa_constants import DOCUMENT_ID_ENDPOINT
from onyx.utils.logger import setup_logger

logger = setup_logger()

# revision identifiers, used by Alembic.
revision = "238736219dd4"
down_revision = "505c488f6662"
branch_labels = None
depends_on = None


def upgrade() -> None:

    # enable pgcrypto
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # Initialize inspector for existence checks
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    # STEP 1: Add any new columns or tables that are not already present

    "===USER_FILE==="
    # add user_file transitional UUID new_id column (only if id is not already UUID)
    user_file_columns_info = inspector.get_columns("user_file")
    existing_columns = [col["name"] for col in user_file_columns_info]
    id_is_uuid = any(
        col["name"] == "id" and "uuid" in str(col["type"]).lower()
        for col in user_file_columns_info
    )
    if "new_id" not in existing_columns and not id_is_uuid:
        op.add_column(
            "user_file",
            sa.Column(
                "new_id",
                psql.UUID(as_uuid=True),
                nullable=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
        )
        op.create_unique_constraint("uq_user_file_new_id", "user_file", ["new_id"])

    if "status" not in existing_columns:
        op.add_column(
            "user_file",
            sa.Column(
                "status",
                sa.Enum(
                    "processing",
                    "completed",
                    "failed",
                    "canceled",
                    name="userfilestatus",
                    native_enum=False,
                ),
                nullable=False,
                server_default="processing",
            ),
        )

    if "chunk_count" not in existing_columns:
        op.add_column(
            "user_file", sa.Column("chunk_count", sa.Integer(), nullable=True)
        )

    if "last_accessed_at" not in existing_columns:
        op.add_column(
            "user_file",
            sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "needs_project_sync" not in existing_columns:
        op.add_column(
            "user_file",
            sa.Column(
                "needs_project_sync",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )
    if "last_project_sync_at" not in existing_columns:
        op.add_column(
            "user_file",
            sa.Column(
                "last_project_sync_at", sa.DateTime(timezone=True), nullable=True
            ),
        )

    "===USER_FOLDER==="
    # make description nullable and rename if the legacy table still exists
    if "user_folder" in table_names:
        op.alter_column("user_folder", "description", nullable=True)
        if "user_project" not in table_names:
            op.execute("ALTER TABLE IF EXISTS user_folder RENAME TO user_project")
    elif "user_project" in table_names:
        # If already renamed, ensure column nullability on the new table
        inspector = sa.inspect(bind)
        project_cols = [col["name"] for col in inspector.get_columns("user_project")]
        if "description" in project_cols:
            op.alter_column("user_project", "description", nullable=True)

    "===USER_PROJECT==="
    inspector = sa.inspect(bind)
    user_project_columns = [
        col["name"] for col in inspector.get_columns("user_project")
    ]
    if "instructions" not in user_project_columns:
        op.add_column(
            "user_project",
            sa.Column("instructions", sa.String(), nullable=True),
        )

    "===CHAT_SESSION==="
    inspector = sa.inspect(bind)
    chat_session_columns = [
        col["name"] for col in inspector.get_columns("chat_session")
    ]
    if "project_id" not in chat_session_columns:
        op.add_column(
            "chat_session",
            sa.Column("project_id", sa.Integer(), nullable=True),
        )
    # add foreign key constraint to chat_session.project_id
    # Check if foreign key already exists before creating
    inspector = sa.inspect(bind)
    chat_session_fks = inspector.get_foreign_keys("chat_session")
    fk_exists = any(
        fk["name"] == "fk_chat_session_project_id" for fk in chat_session_fks
    )

    if not fk_exists:
        op.create_foreign_key(
            "fk_chat_session_project_id",
            "chat_session",
            "user_project",
            ["project_id"],
            ["id"],
        )

    "===PERSONA__USER_FILE==="
    inspector = sa.inspect(bind)
    persona_user_file_columns = [
        col["name"] for col in inspector.get_columns("persona__user_file")
    ]
    if "user_file_id_uuid" not in persona_user_file_columns:
        op.add_column(
            "persona__user_file",
            sa.Column("user_file_id_uuid", psql.UUID(as_uuid=True), nullable=True),
        )

    "===PROJECT__USER_FILE==="
    # foreign key constraint will be added after the userfile id transition is complete
    if "project__user_file" not in table_names:
        op.execute(
            """
            CREATE TABLE IF NOT EXISTS project__user_file (
                project_id INTEGER NOT NULL,
                user_file_id UUID NOT NULL,
                PRIMARY KEY (project_id, user_file_id)
            )
            """
        )
    # add index to project__user_file.user_file_id
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_project__user_file_user_file_id ON project__user_file (user_file_id)"
    )

    # STEP 2: Data preparation and backfill

    # Determine if we're in pre-swap (has new_id) or post-swap state
    inspector = sa.inspect(bind)
    user_file_columns_current_info = inspector.get_columns("user_file")
    user_file_columns_current = [col["name"] for col in user_file_columns_current_info]
    has_new_id = "new_id" in user_file_columns_current
    has_document_id = "document_id" in user_file_columns_current

    # populate user_file.new_id column if present (pre-swap state)
    if has_new_id:
        bind.execute(
            text("UPDATE user_file SET new_id = gen_random_uuid() WHERE new_id IS NULL")
        )

        # Assertions – fail fast (auto-rolls back migration)
        null_new_id = bind.execute(
            sa.text("SELECT COUNT(*) FROM user_file WHERE new_id IS NULL")
        ).scalar_one()
        if null_new_id:
            raise Exception(
                f"user_file.new_id not fully populated ({null_new_id} NULL)"
            )

        # Lock down the new_id column
        op.alter_column("user_file", "new_id", nullable=False)
        op.alter_column("user_file", "new_id", server_default=None)

    # populate persona__user_file.user_file_id_uuid column
    inspector = sa.inspect(bind)
    persona_user_file_columns_curr = [
        col["name"] for col in inspector.get_columns("persona__user_file")
    ]
    if has_new_id and "user_file_id_uuid" in persona_user_file_columns_curr:
        bind.execute(
            text(
                """
            UPDATE persona__user_file p
            SET user_file_id_uuid = uf.new_id
            FROM user_file uf
            WHERE p.user_file_id = uf.id AND p.user_file_id_uuid IS NULL
            """
            )
        )

    # Assertions – fail fast (auto-rolls back migration)
    if (
        "user_file_id_uuid" in persona_user_file_columns_curr
        and "user_file_id" in persona_user_file_columns_curr
    ):
        left_to_fill = bind.execute(
            sa.text(
                """
            SELECT COUNT(*) FROM persona__user_file
            WHERE user_file_id IS NOT NULL AND user_file_id_uuid IS NULL
        """
            )
        ).scalar_one()
        if left_to_fill:
            raise Exception(
                f"persona__user_file.user_file_id_uuid not fully populated ({left_to_fill} rows)"
            )

    if "user_file_id_uuid" in persona_user_file_columns_curr:
        op.alter_column("persona__user_file", "user_file_id_uuid", nullable=False)

    # Move persona__user_folder relationships to persona__user_file relationships
    # For each persona-folder link, link the persona to all files currently in that folder
    if (
        has_new_id
        and "persona__user_folder" in table_names
        and "user_file" in table_names
    ):
        inspector = sa.inspect(bind)
        user_file_columns_for_folder = [
            col["name"] for col in inspector.get_columns("user_file")
        ]
        if "folder_id" in user_file_columns_for_folder:
            bind.execute(
                sa.text(
                    """
            INSERT INTO persona__user_file (persona_id, user_file_id, user_file_id_uuid)
            SELECT puf.persona_id, uf.id, uf.new_id
            FROM persona__user_folder puf
            JOIN user_file uf ON uf.folder_id = puf.user_folder_id
            WHERE NOT EXISTS (
              SELECT 1
              FROM persona__user_file p2
              WHERE p2.persona_id = puf.persona_id
                AND p2.user_file_id = uf.id
            )
            """
                )
            )

    # create user_project records for each chat_folder record
    if "chat_folder" in table_names:
        bind.execute(
            text(
                """
            INSERT INTO user_project (user_id, name)
            SELECT cf.user_id, cf.name
            FROM chat_folder cf
            WHERE NOT EXISTS (
              SELECT 1
              FROM user_project up
              WHERE up.user_id = cf.user_id AND up.name = cf.name
            )
        """
            )
        )

    # populate project_id column in chat_session table
    inspector = sa.inspect(bind)
    chat_session_columns_curr = [
        col["name"] for col in inspector.get_columns("chat_session")
    ]
    if "folder_id" in chat_session_columns_curr:
        bind.execute(
            text(
                """
                UPDATE chat_session cs
                SET project_id = up.id
                FROM chat_folder cf
                JOIN user_project up ON up.user_id = cf.user_id AND up.name = cf.name
                WHERE cs.folder_id = cf.id AND cs.project_id IS NULL;
            """
            )
        )

    # Assertions – fail fast (auto-rolls back migration)
    if "folder_id" in chat_session_columns_curr:
        left_to_fill = bind.execute(
            sa.text(
                """
            SELECT COUNT(*) FROM chat_session
            WHERE project_id IS NULL AND folder_id IS NOT NULL
        """
            )
        ).scalar_one()
        if left_to_fill:
            raise Exception(
                f"chat_session.project_id not fully populated ({left_to_fill} rows)"
            )

    # Populate project__user_file from legacy folder relationships
    # Map each user_file's folder_id (now project id) to its transitional UUID new_id
    if has_new_id:
        inspector = sa.inspect(bind)
        user_file_columns_for_folder = [
            col["name"] for col in inspector.get_columns("user_file")
        ]
        if "folder_id" in user_file_columns_for_folder:
            bind.execute(
                sa.text(
                    """
            INSERT INTO project__user_file (project_id, user_file_id)
            SELECT uf.folder_id AS project_id, uf.new_id AS user_file_id
            FROM user_file uf
            WHERE uf.folder_id IS NOT NULL
            ON CONFLICT (project_id, user_file_id) DO NOTHING
            """
                )
            )

    # Backfill user_file.status based on latest index_attempt for its cc_pair_id
    # - FAILED -> failed
    # - anything else (or missing attempt) -> completed
    # NOTE: legacy schema has user_file.cc_pair_id (unique) for user-file connectors

    bind.execute(
        sa.text(
            """
            WITH latest AS (
                SELECT DISTINCT ON (ia.connector_credential_pair_id)
                    ia.connector_credential_pair_id,
                    ia.status
                FROM index_attempt ia
                ORDER BY ia.connector_credential_pair_id, ia.time_updated DESC
            ),
            uf_to_ccp AS (
                SELECT uf.id AS uf_id, ccp.id AS cc_pair_id
                FROM user_file uf
                JOIN document_by_connector_credential_pair dcc
                    ON dcc.id = uf.document_id
                JOIN connector_credential_pair ccp
                    ON ccp.connector_id = dcc.connector_id
                    AND ccp.credential_id = dcc.credential_id
            )
            UPDATE user_file uf
            SET status = CASE WHEN latest.status = 'failed' THEN 'failed' ELSE 'completed' END
            FROM uf_to_ccp ufc
            LEFT JOIN latest ON latest.connector_credential_pair_id = ufc.cc_pair_id
            WHERE uf.id = ufc.uf_id
            """
        )
    )

    # Update Vespa document_id -> new user_file UUID for legacy user file documents
    # We only touch rows where a legacy user_file.document_id exists (pre-migration), mapping to new_id

    def _active_search_settings() -> tuple[SearchSettings, SearchSettings | None]:
        result = bind.execute(
            sa.text(
                """
            SELECT * FROM search_settings WHERE status = 'PRESENT' ORDER BY id DESC LIMIT 1
            """
            )
        )
        search_settings_fetch = result.fetchall()
        search_settings = (
            SearchSettings(**search_settings_fetch[0]._asdict())
            if search_settings_fetch
            else None
        )

        result2 = bind.execute(
            sa.text(
                """
            SELECT * FROM search_settings WHERE status = 'FUTURE' ORDER BY id DESC LIMIT 1
            """
            )
        )
        search_settings_future_fetch = result2.fetchall()
        search_settings_future = (
            SearchSettings(**search_settings_future_fetch[0]._asdict())
            if search_settings_future_fetch
            else None
        )

        if not isinstance(search_settings, SearchSettings):
            raise RuntimeError(
                "current search settings is of type " + str(type(search_settings))
            )
        if not (
            isinstance(search_settings_future, SearchSettings)
            or search_settings_future is None
        ):
            raise RuntimeError(
                "future search settings is of type " + str(type(search_settings_future))
            )

        return search_settings, search_settings_future

    def _visit_chunks(
        *,
        http_client: httpx.Client,
        index_name: str,
        selection: str,
        continuation: str | None = None,
    ) -> tuple[list[dict], str | None]:
        base_url = DOCUMENT_ID_ENDPOINT.format(index_name=index_name)
        params: dict[str, str] = {
            "selection": selection,
            "wantedDocumentCount": "1000",
        }
        if continuation:
            params["continuation"] = continuation
        resp = http_client.get(base_url, params=params, timeout=None)
        resp.raise_for_status()
        payload = resp.json()
        return payload.get("documents", []), payload.get("continuation")

    def _normalize_legacy_user_file_doc_id(old_id: str) -> str:
        """Convert USER_FILE_CONNECTOR__<uuid> -> FILE_CONNECTOR__<uuid>. Otherwise return as-is."""
        user_prefix = "USER_FILE_CONNECTOR__"
        file_prefix = "FILE_CONNECTOR__"
        if old_id.startswith(user_prefix):
            remainder = old_id[len(user_prefix) :]
            return file_prefix + remainder
        return old_id

    def _update_document_id_in_vespa(
        index_name: str, old_doc_id: str, new_doc_id: str
    ) -> None:
        clean_new_doc_id = replace_invalid_doc_id_characters(new_doc_id)
        # Selection must use the Vespa-afied doc id to match stored values
        normalized_old = _normalize_legacy_user_file_doc_id(old_doc_id)
        clean_old_doc_id = replace_invalid_doc_id_characters(normalized_old)

        # Use single quotes for Document Selector Language to match existing working code
        selection = f"{index_name}.document_id=='{clean_old_doc_id}'"
        print(f"selection: {selection}")
        with get_vespa_http_client() as http_client:
            continuation: str | None = None
            while True:
                docs, continuation = _visit_chunks(
                    http_client=http_client,
                    index_name=index_name,
                    selection=selection,
                    continuation=continuation,
                )
                print(f"docs: {docs}")
                print(f"continuation: {continuation}")
                if not docs:
                    break
                for doc in docs:
                    vespa_full_id = doc.get("id")
                    if not vespa_full_id:
                        continue
                    print(f"vespa_full_id: {vespa_full_id}")
                    vespa_doc_uuid = vespa_full_id.split("::")[-1]
                    vespa_url = f"{DOCUMENT_ID_ENDPOINT.format(index_name=index_name)}/{vespa_doc_uuid}"
                    print(f"vespa_url: {vespa_url}")
                    update_request = {
                        "fields": {"document_id": {"assign": clean_new_doc_id}}
                    }
                    r = http_client.put(vespa_url, json=update_request)
                    print(f"r: {r}")
                    r.raise_for_status()
                if not continuation:
                    break

    try:
        print("Updating search_doc.document_id to user_file UUIDs (string)")
        # Acquire index name from active search settings
        current_ss, future_ss = _active_search_settings()
        print(f"current_ss: {current_ss}")
        print(f"future_ss: {future_ss}")
        document_index = get_default_document_index(current_ss, future_ss)
        print(f"document_index: {document_index}")
        if hasattr(document_index, "index_name"):
            index_name = document_index.index_name
        else:
            index_name = "danswer_index"

        # Fetch legacy mappings from user_file only if both columns exist
        print(f"has_new_id: {has_new_id}")
        print(f"has_document_id: {has_document_id}")
        if has_new_id and has_document_id:
            mappings = bind.execute(
                sa.text(
                    """
                    SELECT document_id, new_id
                    FROM user_file
                    WHERE document_id IS NOT NULL
                    """
                )
            ).fetchall()
        else:
            mappings = []

        # Deduplicate by old document_id to avoid repeated updates
        seen: set[str] = set()
        print(f"mappings: {mappings}")
        for row in mappings:
            old_doc_id = str(row.document_id)
            new_uuid = str(row.new_id)
            if not old_doc_id or not new_uuid:
                continue
            if old_doc_id in seen:
                continue
            seen.add(old_doc_id)
            try:
                print(f"updating Vespa document_id for {old_doc_id} -> {new_uuid}")
                _update_document_id_in_vespa(index_name, old_doc_id, new_uuid)
            except Exception as e:
                print(
                    f"Failed to update Vespa document_id for {old_doc_id} -> {new_uuid}: {e}"
                )

        # Update search_doc.document_id to user_file UUIDs (string)
        if has_new_id and has_document_id:
            bind.execute(
                sa.text(
                    """
                UPDATE search_doc sd
                SET document_id = uf.new_id::text
                FROM user_file uf
                WHERE uf.document_id IS NOT NULL
                  AND sd.document_id = uf.document_id
                    """
                )
            )
    except Exception as e:
        print(f"Error updating Vespa document_id: {e}")
        print(f"Skipping Vespa/search_doc updates step: {e}")

    # Helper function to perform batch deletions
    def batch_delete(
        table_name: str, id_column: str, ids: list, batch_size: int = 1000
    ) -> None:
        """Delete records in batches to avoid memory issues and timeouts."""
        total_count = len(ids)
        if total_count == 0:
            return

        print(f"Starting batch deletion of {total_count} records from {table_name}...")

        for i in range(0, total_count, batch_size):
            batch_ids = ids[i : i + batch_size]
            bind.execute(
                sa.text(f"DELETE FROM {table_name} WHERE {id_column} = ANY(:ids)"),
                {"ids": batch_ids},
            )

            # Log progress every 10 batches or at completion
            batch_num = (i // batch_size) + 1
            if batch_num % 10 == 0 or i + batch_size >= total_count:
                print(
                    f"  Deleted {min(i + batch_size, total_count)}/{total_count} records from {table_name}"
                )

    # Remove legacy user-file cc_pairs and all related document rows
    # 1) Identify user-file cc_pairs and their (connector_id, credential_id)
    # Intentionally preserve search_doc and its linking tables; we updated search_doc.document_id earlier
    # so chat replay remains intact. Skip deleting agent__sub_query__search_doc, chat_message__search_doc, search_doc.
    #
    # IMPORTANT: Select the target document IDs into Python to avoid temp tables with async drivers
    doc_rows = bind.execute(
        sa.text(
            """
        SELECT DISTINCT dcc.id AS document_id
        FROM document_by_connector_credential_pair dcc
        JOIN connector_credential_pair u
          ON u.connector_id = dcc.connector_id
         AND u.credential_id = dcc.credential_id
        WHERE u.is_user_file IS TRUE
        """
        )
    ).fetchall()
    doc_ids = [r[0] for r in doc_rows]

    if doc_ids:
        print(f"Found {len(doc_ids)} documents to delete")

        # Delete dependent rows that FK reference document.id
        batch_delete("document_retrieval_feedback", "document_id", doc_ids)
        batch_delete("document__tag", "document_id", doc_ids)
        batch_delete("chunk_stats", "document_id", doc_ids)

        # Delete per-ccpair doc mapping and then the documents themselves
        batch_delete("document_by_connector_credential_pair", "id", doc_ids)
        batch_delete("document", "id", doc_ids)
    # Get user-file cc_pair IDs for batch deletion
    cc_pair_rows = bind.execute(
        sa.text(
            """
            SELECT id AS cc_pair_id
            FROM connector_credential_pair
            WHERE is_user_file IS TRUE
            """
        )
    ).fetchall()
    cc_pair_ids = [r[0] for r in cc_pair_rows]

    if cc_pair_ids:
        print(
            f"Found {len(cc_pair_ids)} user-file connector_credential_pairs to clean up"
        )

        # Delete index_attempt records in batches
        batch_delete("index_attempt", "connector_credential_pair_id", cc_pair_ids)

        # Delete background_error records in batches
        batch_delete("background_error", "cc_pair_id", cc_pair_ids)
    # Note: do not delete connector_credential_pair yet; user_file still has FK to it.

    # STEP 3: Cleanup legacy folder-related tables/columns now that data is migrated

    # Before deleting user-file connector_credential_pair rows, remove any
    # relationships that depend on those cc_pairs to avoid FK violations.
    # We can reuse the cc_pair_ids from above if they exist, otherwise fetch them
    if "cc_pair_ids" not in locals() or not cc_pair_ids:
        cc_pair_rows = bind.execute(
            sa.text(
                """
                SELECT id AS cc_pair_id
                FROM connector_credential_pair
                WHERE is_user_file IS TRUE
                """
            )
        ).fetchall()
        cc_pair_ids = [r[0] for r in cc_pair_rows]

    if cc_pair_ids:
        # Delete document_set__connector_credential_pair records in batches
        batch_delete(
            "document_set__connector_credential_pair",
            "connector_credential_pair_id",
            cc_pair_ids,
        )

        # Delete user_group__connector_credential_pair records in batches
        batch_delete("user_group__connector_credential_pair", "cc_pair_id", cc_pair_ids)

    # Rewire persona__user_file to UUID FK (user_file_id_uuid -> user_file.new_id), drop old int, then rename.
    # Refresh inspector to avoid stale schema cache
    inspector = sa.inspect(bind)
    persona_user_file_cols_after = [
        col["name"] for col in inspector.get_columns("persona__user_file")
    ]
    # If uuid column is missing but legacy int column exists, add and backfill now
    if (
        "user_file_id_uuid" not in persona_user_file_cols_after
        and "user_file_id" in persona_user_file_cols_after
    ):
        # Ensure the new UUID column exists for transition
        op.add_column(
            "persona__user_file",
            sa.Column("user_file_id_uuid", psql.UUID(as_uuid=True), nullable=True),
        )
        # Backfill from legacy int id -> user_file.new_id before we swap PKs
        bind.execute(
            text(
                """
            UPDATE persona__user_file p
            SET user_file_id_uuid = uf.new_id
            FROM user_file uf
            WHERE p.user_file_id = uf.id AND p.user_file_id_uuid IS NULL
            """
            )
        )
        op.alter_column("persona__user_file", "user_file_id_uuid", nullable=False)
        # Refresh columns list
        inspector = sa.inspect(bind)
        persona_user_file_cols_after = [
            col["name"] for col in inspector.get_columns("persona__user_file")
        ]
    if "user_file_id_uuid" in persona_user_file_cols_after:
        op.execute(
            "ALTER TABLE persona__user_file DROP CONSTRAINT IF EXISTS persona__user_file_user_file_id_uuid_fkey"
        )
        op.execute(
            "ALTER TABLE persona__user_file DROP CONSTRAINT IF EXISTS persona__user_file_user_file_id_fkey"
        )
        # Choose remote column based on current state (before/after swap)
        inspector = sa.inspect(bind)
        user_file_cols_now = [col["name"] for col in inspector.get_columns("user_file")]
        remote_col = "new_id" if "new_id" in user_file_cols_now else "id"
        op.create_foreign_key(
            "persona__user_file_user_file_id_fkey",
            "persona__user_file",
            "user_file",
            local_cols=["user_file_id_uuid"],
            remote_cols=[remote_col],
        )
        op.execute("ALTER TABLE persona__user_file DROP COLUMN IF EXISTS user_file_id")
        op.alter_column(
            "persona__user_file",
            "user_file_id_uuid",
            new_column_name="user_file_id",
            existing_type=psql.UUID(as_uuid=True),
            nullable=False,
        )

    # Ensure composite primary key on (persona_id, user_file_id)
    op.execute(
        "ALTER TABLE persona__user_file DROP CONSTRAINT IF EXISTS persona__user_file_pkey"
    )
    # Check if primary key already exists before adding
    inspector = sa.inspect(bind)
    pk_constraint = inspector.get_pk_constraint("persona__user_file")
    pk_exists = (
        pk_constraint is not None
        and len(pk_constraint.get("constrained_columns", [])) > 0
    )

    if not pk_exists:
        op.execute(
            "ALTER TABLE persona__user_file ADD PRIMARY KEY (persona_id, user_file_id)"
        )

    # Finalize UUID swap on user_file: new_id -> id (set as PK)
    # Refresh inspector to avoid cached reflection before checking final schema
    inspector = sa.inspect(bind)
    user_file_columns_after = [
        col["name"] for col in inspector.get_columns("user_file")
    ]
    print(f"user_file_columns_after: {user_file_columns_after}")
    if "new_id" in user_file_columns_after:
        # Drop dependent FKs before changing PK to avoid dependency errors
        op.execute(
            "ALTER TABLE persona__user_file DROP CONSTRAINT IF EXISTS persona__user_file_user_file_id_fkey"
        )
        op.execute("ALTER TABLE user_file DROP CONSTRAINT IF EXISTS user_file_pkey")
        # Ensure we don't collide with an existing id column from older states
        op.execute("ALTER TABLE user_file DROP COLUMN IF EXISTS id")
        op.alter_column(
            "user_file",
            "new_id",
            new_column_name="id",
            existing_type=psql.UUID(as_uuid=True),
            nullable=False,
        )
        # Check if primary key already exists before adding
        inspector = sa.inspect(bind)
        pk_constraint = inspector.get_pk_constraint("user_file")
        pk_exists = (
            pk_constraint is not None
            and len(pk_constraint.get("constrained_columns", [])) > 0
        )

        if not pk_exists:
            op.execute("ALTER TABLE user_file ADD PRIMARY KEY (id)")
        # Drop the unique constraint on new_id (now on id) before recreating FKs
        # so that the FK binds to the primary key index rather than this unique index.
        op.execute(
            "ALTER TABLE user_file DROP CONSTRAINT IF EXISTS uq_user_file_new_id"
        )
        # Recreate FK now that PK is swapped to UUID id
        inspector = sa.inspect(bind)
        persona_cols_info = inspector.get_columns("persona__user_file")
        col_types = {c["name"]: str(c["type"]).lower() for c in persona_cols_info}
        if "user_file_id" in col_types and "uuid" in col_types["user_file_id"]:
            local_fk_col = "user_file_id"
        elif (
            "user_file_id_uuid" in col_types
            and "uuid" in col_types["user_file_id_uuid"]
        ):
            local_fk_col = "user_file_id_uuid"
        else:
            local_fk_col = None

        if local_fk_col is not None:
            op.create_foreign_key(
                "persona__user_file_user_file_id_fkey",
                "persona__user_file",
                "user_file",
                local_cols=[local_fk_col],
                remote_cols=["id"],
            )
        else:
            logger.warning(
                "Skipping FK recreation persona__user_file->user_file due to non-UUID local column"
            )

    # Drop chat_session.folder_id foreign key and column (if exist)
    op.execute(
        "ALTER TABLE chat_session DROP CONSTRAINT IF EXISTS chat_session_folder_fk"
    )
    op.execute("ALTER TABLE chat_session DROP COLUMN IF EXISTS folder_id")

    # Drop persona__user_folder and chat_folder if exist
    op.execute("DROP TABLE IF EXISTS persona__user_folder")
    op.execute("DROP TABLE IF EXISTS chat_folder")

    # Drop user_file.folder_id if exist
    op.execute("ALTER TABLE user_file DROP COLUMN IF EXISTS folder_id")

    # Drop any FKs from user_file to connector_credential_pair (name-agnostic), then drop column
    bind.execute(
        sa.text(
            """
        DO $$
        DECLARE r RECORD;
        BEGIN
          FOR r IN (
            SELECT conname
            FROM pg_constraint c
            JOIN pg_class t ON c.conrelid = t.oid
            JOIN pg_class ft ON c.confrelid = ft.oid
            WHERE c.contype = 'f'
              AND t.relname = 'user_file'
              AND ft.relname = 'connector_credential_pair'
          ) LOOP
            EXECUTE format('ALTER TABLE user_file DROP CONSTRAINT %I', r.conname);
          END LOOP;
        END$$;
        """
        )
    )
    # Also drop named unique/index constraints if present (best-effort)
    op.execute(
        "ALTER TABLE user_file DROP CONSTRAINT IF EXISTS user_file_cc_pair_id_key"
    )
    op.execute("ALTER TABLE user_file DROP COLUMN IF EXISTS cc_pair_id")

    # Now safe to delete the user-file cc_pairs themselves
    # Compute target connectors/credentials that are exclusively tied to user-file cc_pairs
    # BEFORE deleting those cc_pairs. This ensures we only delete entities where the cc_pairs
    # are is_user_file=TRUE (and not shared with non-user-file cc_pairs).
    # Compute exclusive user-file connectors/credentials in Python (avoid temp tables)
    connector_rows = bind.execute(
        sa.text(
            """
        SELECT DISTINCT ccp.connector_id
        FROM connector_credential_pair ccp
        WHERE ccp.is_user_file IS TRUE
          AND NOT EXISTS (
            SELECT 1
            FROM connector_credential_pair c2
            WHERE c2.connector_id = ccp.connector_id
              AND c2.is_user_file IS NOT TRUE
          )
        """
        )
    ).fetchall()
    userfile_only_connector_ids = [r[0] for r in connector_rows]
    credential_rows = bind.execute(
        sa.text(
            """
        SELECT DISTINCT ccp.credential_id
        FROM connector_credential_pair ccp
        WHERE ccp.is_user_file IS TRUE
          AND NOT EXISTS (
            SELECT 1
            FROM connector_credential_pair c2
            WHERE c2.credential_id = ccp.credential_id
              AND c2.is_user_file IS NOT TRUE
          )
        """
        )
    ).fetchall()
    userfile_only_credential_ids = [r[0] for r in credential_rows]

    # Now delete the user-file cc_pairs in batches
    # First get all user-file cc_pair IDs for batch deletion
    cc_pair_rows = bind.execute(
        sa.text(
            """
            SELECT id FROM connector_credential_pair
            WHERE is_user_file IS TRUE
            """
        )
    ).fetchall()
    cc_pair_ids_to_delete = [r[0] for r in cc_pair_rows]

    if cc_pair_ids_to_delete:
        batch_delete("connector_credential_pair", "id", cc_pair_ids_to_delete)

    # Delete only connectors that were exclusively user-file (exclude system default id=0)
    if userfile_only_connector_ids:
        filtered_connectors = [i for i in userfile_only_connector_ids if i != 0]
        if filtered_connectors:
            batch_delete("connector", "id", filtered_connectors)

    # Delete only credentials that were exclusively user-file (exclude public/default id=0)
    # First clean up related user group mappings for those credentials
    if userfile_only_credential_ids:
        filtered_creds = [i for i in userfile_only_credential_ids if i != 0]
        if filtered_creds:
            # Delete credential__user_group mappings in batches
            batch_delete("credential__user_group", "credential_id", filtered_creds)

            # Delete credentials in batches
            batch_delete("credential", "id", filtered_creds)

    # Drop legacy user_file.document_id now that Vespa/search_doc are updated
    op.execute("ALTER TABLE user_file DROP COLUMN IF EXISTS document_id")
