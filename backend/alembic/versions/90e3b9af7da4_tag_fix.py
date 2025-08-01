"""tag-fix

Revision ID: 90e3b9af7da4
Revises: 3fc5d75723b3
Create Date: 2025-08-01 20:58:14.607624

"""

import os

from alembic import op
import sqlalchemy as sa
from onyx.utils.logger import setup_logger

logger = setup_logger()


# revision identifiers, used by Alembic.
revision = "90e3b9af7da4"
down_revision = "3fc5d75723b3"
branch_labels = None
depends_on = None

# FIXME: set true before merge
SKIP_TAG_FIX = os.environ.get("SKIP_TAG_FIX", "false").lower() == "true"


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
            sa.text(
                f"""
                UPDATE document__tag AS dt
                SET is_list = true
                FROM tag
                WHERE tag.id = dt.tag_id
                AND tag.tag_key = '{key}'
                AND tag.source = '{source}'
                """
            )
        )


def set_is_list_for_list_tags() -> None:
    """
    Sets is_list to true for all tags which have multiple values for a given
    document, key, and source triplet. This only works if we remove old tags
    from the database.
    """
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE document__tag AS dt
            SET is_list = true
            FROM (
                SELECT DISTINCT tag.tag_key, tag.source
                FROM tag
                JOIN document__tag ON tag.id = document__tag.tag_id
                GROUP BY tag.tag_key, tag.source, document__tag.document_id
                HAVING count(*) > 1
            ) AS list_tags
            JOIN tag ON tag.tag_key = list_tags.tag_key AND tag.source = list_tags.source
            WHERE dt.tag_id = tag.id
            """
        )
    )


def print_list_tags() -> None:
    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            """
            SELECT DISTINCT source, tag_key FROM document__tag
            JOIN tag ON tag.id = document__tag.tag_id
            WHERE is_list
            ORDER BY source, tag_key
            """
        )
    ).fetchall()
    print("List tags:\n" + "\n".join(f"  {source}: {key}" for source, key in result))


def remove_old_tags() -> None:
    """
    Removes old tags from the database.
    Previously, there was a bug where if a document got indexed with a tag and then
    the document got reindexed, the old tag would not be removed.
    This function removes those old tags by comparing it against the tags in vespa.
    """
    # TODO:


def upgrade() -> None:
    op.add_column(
        "document__tag",
        sa.Column("is_list", sa.Boolean(), nullable=False, server_default="false"),
    )
    set_is_list_for_known_tags()

    if SKIP_TAG_FIX:
        logger.warning(
            "Skipping removal of old tags. "
            "This can cause issues when using the knowledge graph, or "
            "when filtering for documents by tags."
        )
        print_list_tags()
        return

    remove_old_tags()
    set_is_list_for_list_tags()

    # debug
    print_list_tags()


def downgrade() -> None:
    # the migration adds and populates the is_list column, and removes old bugged tags
    # there isn't a point in adding back the bugged tags, so we just drop the column
    op.drop_column("document__tag", "is_list")
