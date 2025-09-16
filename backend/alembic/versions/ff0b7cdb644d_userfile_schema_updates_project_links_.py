"""userfile_schema_updates_project_links_and_cleanup

Revision ID: ff0b7cdb644d
Revises: b7ec9b5b505f
Create Date: 2025-09-16 11:39:18.830018

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
revision = "ff0b7cdb644d"
down_revision = "b7ec9b5b505f"
branch_labels = None
depends_on = None


def upgrade() -> None:

    # enable pgcrypto
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # STEP 1: Add any new columns or tables that are not already present

    "===USER_FILE==="
    # add user_file transitional UUID new_id column
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

    op.add_column("user_file", sa.Column("chunk_count", sa.Integer(), nullable=True))

    op.add_column(
        "user_file",
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "user_file",
        sa.Column("needs_project_sync", sa.Boolean(), nullable=False, default=False),
    )
    op.add_column(
        "user_file",
        sa.Column("last_project_sync_at", sa.DateTime(timezone=True), nullable=True),
    )

    "===USER_PROJECT==="
    op.add_column(
        "user_project",
        sa.Column("instructions", sa.String(), nullable=True),
    )

    "===CHAT_SESSION==="
    op.add_column(
        "chat_session",
        sa.Column("project_id", sa.Integer(), nullable=True),
    )
    # add foreign key constraint to chat_session.project_id
    op.create_foreign_key(
        "fk_chat_session_project_id",
        "chat_session",
        "user_project",
        ["project_id"],
        ["id"],
    )

    "===PERSONA__USER_FILE==="
    op.add_column(
        "persona__user_file",
        sa.Column("user_file_id_uuid", psql.UUID(as_uuid=True), nullable=True),
    )

    "===PROJECT__USER_FILE==="
    # foreign key constraint will be added after the userfile id transition is complete
    op.create_table(
        "project__user_file",
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("user_file_id", psql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("project_id", "user_file_id"),
    )
    # add index to project__user_file.user_file_id
    op.create_index(
        "idx_project__user_file_user_file_id", "project__user_file", ["user_file_id"]
    )

    "===USER_FOLDER==="
    # make description nullable
    op.alter_column("user_folder", "description", nullable=True)
    op.rename_table("user_folder", "user_project")

    # STEP 2: Data preparation and backfill
    conn = op.get_bind()

    # populate user_file.new_id column
    conn.execute(
        text("UPDATE user_file SET new_id = gen_random_uuid() WHERE new_id IS NULL")
    )

    # Assertions – fail fast (auto-rolls back migration)
    null_new_id = conn.execute(
        sa.text("SELECT COUNT(*) FROM user_file WHERE new_id IS NULL")
    ).scalar_one()
    if null_new_id:
        raise Exception(f"user_file.new_id not fully populated ({null_new_id} NULL)")

    # Lock down the new_id column
    op.alter_column("user_file", "new_id", nullable=False)
    op.alter_column("user_file", "new_id", server_default=None)

    # populate persona__user_file.user_file_id_uuid column
    conn.execute(
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
    left_to_fill = conn.execute(
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

    op.alter_column("persona__user_file", "user_file_id_uuid", nullable=False)

    # create user_project records for each chat_folder record
    conn.execute(
        text(
            """
        INSERT INTO user_project (user_id, name)
        SELECT user_id, name FROM chat_folder
    """
        )
    )

    # populate project_id column in chat_session table
    conn.execute(
        text(
            """
        UPDATE chat_session cs
        SET project_id = up.id
        FROM user_project up
        WHERE cs.folder_id = up.id
    """
        )
    )

    # Assertions – fail fast (auto-rolls back migration)
    left_to_fill = conn.execute(
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

    # Backfill user_file.status based on latest index_attempt for its cc_pair_id
    # - FAILED -> failed
    # - anything else (or missing attempt) -> completed
    # NOTE: legacy schema has user_file.cc_pair_id (unique) for user-file connectors

    conn.execute(
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
        result = conn.execute(
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

        result2 = conn.execute(
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

    def _update_document_id_in_vespa(
        index_name: str, old_doc_id: str, new_doc_id: str
    ) -> None:
        clean_new_doc_id = replace_invalid_doc_id_characters(new_doc_id)
        selection = f'{index_name}.document_id=="{old_doc_id}"'
        with get_vespa_http_client() as http_client:
            continuation: str | None = None
            while True:
                docs, continuation = _visit_chunks(
                    http_client=http_client,
                    index_name=index_name,
                    selection=selection,
                    continuation=continuation,
                )
                if not docs:
                    break
                for doc in docs:
                    vespa_full_id = doc.get("id")
                    if not vespa_full_id:
                        continue
                    vespa_doc_uuid = vespa_full_id.split("::")[-1]
                    vespa_url = f"{DOCUMENT_ID_ENDPOINT.format(index_name=index_name)}/{vespa_doc_uuid}"
                    update_request = {
                        "fields": {"document_id": {"assign": clean_new_doc_id}}
                    }
                    r = http_client.put(vespa_url, json=update_request)
                    r.raise_for_status()
                if not continuation:
                    break

    try:
        # Acquire index name from active search settings
        current_ss, future_ss = _active_search_settings()
        document_index = get_default_document_index(current_ss, future_ss)
        if hasattr(document_index, "index_name"):
            index_name = document_index.index_name
        else:
            index_name = "danswer_index"

        # Fetch legacy mappings from user_file
        mappings = conn.execute(
            sa.text(
                """
                SELECT document_id, new_id
                FROM user_file
                WHERE document_id IS NOT NULL
                """
            )
        ).fetchall()

        # Deduplicate by old document_id to avoid repeated updates
        seen: set[str] = set()
        for row in mappings:
            old_doc_id = str(row.document_id)
            new_uuid = str(row.new_id)
            if not old_doc_id or not new_uuid:
                continue
            if old_doc_id in seen:
                continue
            seen.add(old_doc_id)
            try:
                _update_document_id_in_vespa(index_name, old_doc_id, new_uuid)
            except Exception as e:
                logger.warning(
                    f"Failed to update Vespa document_id for {old_doc_id} -> {new_uuid}: {e}"
                )
    except Exception as e:
        logger.warning(f"Skipping Vespa document_id update step: {e}")
