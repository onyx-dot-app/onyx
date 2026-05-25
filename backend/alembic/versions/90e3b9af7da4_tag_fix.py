"""tag-fix

Revision ID: 90e3b9af7da4
Revises: 62c3a055a141
Create Date: 2025-08-01 20:58:14.607624

"""

import logging
import os

from typing import cast
from typing import Generator

from alembic import op
import sqlalchemy as sa

from onyx.db.search_settings import SearchSettings
from onyx.configs.app_configs import AUTH_TYPE
from onyx.configs.constants import AuthType

# NOTE: Vespa-side tag reconciliation was removed in the Vespa removal phase.
# The remove_old_tags step now defaults to a no-op; DB-side schema changes still run.

logger = logging.getLogger("alembic.runtime.migration")


# revision identifiers, used by Alembic.
revision = "90e3b9af7da4"
down_revision = "62c3a055a141"
branch_labels = None
depends_on = None

SKIP_TAG_FIX = os.environ.get("SKIP_TAG_FIX", "true").lower() == "true"

# override for cloud
if AUTH_TYPE == AuthType.CLOUD:
    SKIP_TAG_FIX = True


def set_is_list_for_known_tags() -> None:
    """
    Sets is_list to true for all tags that are known to be lists.
    """
    LIST_METADATA: list[tuple[str, str]] = [
        ("CLICKUP", "tags"),
        ("CONFLUENCE", "labels"),
        ("DISCOURSE", "tags"),
        ("FRESHDESK", "emails"),
        ("GITHUB", "assignees"),
        ("GITHUB", "labels"),
        ("GURU", "tags"),
        ("GURU", "folders"),
        ("HUBSPOT", "associated_contact_ids"),
        ("HUBSPOT", "associated_company_ids"),
        ("HUBSPOT", "associated_deal_ids"),
        ("HUBSPOT", "associated_ticket_ids"),
        ("JIRA", "labels"),
        ("MEDIAWIKI", "categories"),
        ("ZENDESK", "labels"),
        ("ZENDESK", "content_tags"),
    ]

    bind = op.get_bind()
    for source, key in LIST_METADATA:
        bind.execute(
            sa.text(f"""
                UPDATE tag
                SET is_list = true
                WHERE tag_key = '{key}'
                AND source = '{source}'
                """)
        )


def set_is_list_for_list_tags() -> None:
    """
    Sets is_list to true for all tags which have multiple values for a given
    document, key, and source triplet. This only works if we remove old tags
    from the database.
    """
    bind = op.get_bind()
    bind.execute(
        sa.text("""
            UPDATE tag
            SET is_list = true
            FROM (
                SELECT DISTINCT tag.tag_key, tag.source
                FROM tag
                JOIN document__tag ON tag.id = document__tag.tag_id
                GROUP BY tag.tag_key, tag.source, document__tag.document_id
                HAVING count(*) > 1
            ) AS list_tags
            WHERE tag.tag_key = list_tags.tag_key
            AND tag.source = list_tags.source
            """)
    )


def log_list_tags() -> None:
    bind = op.get_bind()
    result = bind.execute(
        sa.text("""
            SELECT DISTINCT source, tag_key
            FROM tag
            WHERE is_list
            ORDER BY source, tag_key
            """)
    ).fetchall()
    logger.info(
        "List tags:\n" + "\n".join(f"  {source}: {key}" for source, key in result)
    )


def remove_old_tags() -> None:
    """No-op since the Vespa removal. The original behavior compared DB tags against
    Vespa-side document metadata to drop stale rows; without a Vespa source of truth
    we can't safely identify which DB tags are stale, so this step is skipped."""
    logger.warning(
        "Skipping remove_old_tags (Vespa removed; no source of truth to reconcile against)"
    )


def active_search_settings() -> tuple[SearchSettings, SearchSettings | None]:
    result = op.get_bind().execute(
        sa.text("""
        SELECT * FROM search_settings WHERE status = 'PRESENT' ORDER BY id DESC LIMIT 1
        """)
    )
    search_settings_fetch = result.fetchall()
    search_settings = (
        SearchSettings(**search_settings_fetch[0]._asdict())
        if search_settings_fetch
        else None
    )

    result2 = op.get_bind().execute(
        sa.text("""
        SELECT * FROM search_settings WHERE status = 'FUTURE' ORDER BY id DESC LIMIT 1
        """)
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
    if (
        not isinstance(search_settings_future, SearchSettings)
        and search_settings_future is not None
    ):
        raise RuntimeError(
            "future search settings is of type " + str(type(search_settings_future))
        )

    return search_settings, search_settings_future


def _get_batch_documents_with_multiple_tags(
    batch_size: int = 128,
) -> Generator[list[str], None, None]:
    """
    Returns a list of document ids which contain a one to many tag.
    The document may either contain a list metadata value, or may contain leftover
    old tags from reindexing.
    """
    offset_clause = ""
    bind = op.get_bind()

    while True:
        batch = bind.execute(
            sa.text(f"""
                SELECT DISTINCT document__tag.document_id
                FROM tag
                JOIN document__tag ON tag.id = document__tag.tag_id
                GROUP BY tag.tag_key, tag.source, document__tag.document_id
                HAVING count(*) > 1 {offset_clause}
                ORDER BY document__tag.document_id
                LIMIT {batch_size}
                """)
        ).fetchall()
        if not batch:
            break
        doc_ids = [document_id for (document_id,) in batch]
        yield doc_ids
        offset_clause = f"AND document__tag.document_id > '{doc_ids[-1]}'"


def _get_vespa_metadata(
    document_id: str, index_name: str
) -> dict[str, str | list[str]]:
    """No-op stub. Vespa has been removed; this migration's old-tag reconciliation
    step no longer has a source of truth to compare against and is skipped."""
    logger.warning(
        "Skipping Vespa metadata lookup for tag reconciliation (Vespa removed): "
        "document_id=%s index_name=%s",
        document_id,
        index_name,
    )
    return {}


def _get_document_tags(document_id: str) -> list[tuple[int, str, str]]:
    bind = op.get_bind()
    result = bind.execute(
        sa.text(f"""
            SELECT tag.id, tag.tag_key, tag.tag_value
            FROM tag
            JOIN document__tag ON tag.id = document__tag.tag_id
            WHERE document__tag.document_id = '{document_id}'
            """)
    ).fetchall()
    return cast(list[tuple[int, str, str]], result)


def upgrade() -> None:
    op.add_column(
        "tag",
        sa.Column("is_list", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.drop_constraint(
        constraint_name="_tag_key_value_source_uc",
        table_name="tag",
        type_="unique",
    )
    op.create_unique_constraint(
        constraint_name="_tag_key_value_source_list_uc",
        table_name="tag",
        columns=["tag_key", "tag_value", "source", "is_list"],
    )
    set_is_list_for_known_tags()

    if SKIP_TAG_FIX:
        logger.warning(
            "Skipping removal of old tags. "
            "This can cause issues when using the knowledge graph, or "
            "when filtering for documents by tags."
        )
        log_list_tags()
        return

    remove_old_tags()
    set_is_list_for_list_tags()

    # debug
    log_list_tags()


def downgrade() -> None:
    # the migration adds and populates the is_list column, and removes old bugged tags
    # there isn't a point in adding back the bugged tags, so we just drop the column
    op.drop_constraint(
        constraint_name="_tag_key_value_source_list_uc",
        table_name="tag",
        type_="unique",
    )
    op.create_unique_constraint(
        constraint_name="_tag_key_value_source_uc",
        table_name="tag",
        columns=["tag_key", "tag_value", "source"],
    )
    op.drop_column("tag", "is_list")
