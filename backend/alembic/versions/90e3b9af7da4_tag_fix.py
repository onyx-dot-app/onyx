"""tag-fix

Revision ID: 90e3b9af7da4
Revises: 62c3a055a141
Create Date: 2025-08-01 20:58:14.607624

"""

import json
import logging
import os

from typing import cast
from typing import Generator

from alembic import op
import sqlalchemy as sa

from onyx.document_index.factory import get_default_document_index
from onyx.document_index.vespa_constants import DOCUMENT_ID_ENDPOINT
from onyx.db.search_settings import SearchSettings
from onyx.configs.app_configs import AUTH_TYPE
from onyx.configs.constants import AuthType
from onyx.document_index.vespa.shared_utils.utils import get_vespa_http_client

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
            sa.text(
                f"""
                UPDATE tag
                SET is_list = true
                WHERE tag_key = '{key}'
                AND source = '{source}'
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
            """
        )
    )


def log_list_tags() -> None:
    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            """
            SELECT DISTINCT source, tag_key
            FROM tag
            WHERE is_list
            ORDER BY source, tag_key
            """
        )
    ).fetchall()
    logger.info(
        "List tags:\n" + "\n".join(f"  {source}: {key}" for source, key in result)
    )


def remove_old_tags() -> None:
    """
    Removes old tags from the database.
    Previously, there was a bug where if a document got indexed with a tag and then
    the document got reindexed, the old tag would not be removed.
    This function removes those old tags by comparing it against the tags in vespa.
    """
    current_search_settings, future_search_settings = active_search_settings()
    document_index = get_default_document_index(
        current_search_settings, future_search_settings
    )

    # Get the index name
    if hasattr(document_index, "index_name"):
        index_name = document_index.index_name
    else:
        # Default index name if we can't get it from the document_index
        index_name = "danswer_index"

    for batch in _get_batch_documents_with_multiple_tags():
        n_deleted = 0

        for document_id in batch:
            true_metadata = _get_vespa_metadata(document_id, index_name)
            tags = _get_document_tags(document_id)

            # identify document__tags to delete
            to_delete: list[str] = []
            for tag_id, tag_key, tag_value in tags:
                true_val = true_metadata.get(tag_key, "")
                if (isinstance(true_val, list) and tag_value not in true_val) or (
                    isinstance(true_val, str) and tag_value != true_val
                ):
                    to_delete.append(str(tag_id))

            if not to_delete:
                continue

            # delete old document__tags
            bind = op.get_bind()
            result = bind.execute(
                sa.text(
                    f"""
                    DELETE FROM document__tag
                    WHERE document_id = '{document_id}'
                    AND tag_id IN ({','.join(to_delete)})
                    """
                )
            )
            n_deleted += result.rowcount
        logger.info(f"Processed {len(batch)} documents and deleted {n_deleted} tags")


def active_search_settings() -> tuple[SearchSettings, SearchSettings | None]:
    result = op.get_bind().execute(
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

    result2 = op.get_bind().execute(
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
            sa.text(
                f"""
                SELECT DISTINCT document__tag.document_id
                FROM tag
                JOIN document__tag ON tag.id = document__tag.tag_id
                GROUP BY tag.tag_key, tag.source, document__tag.document_id
                HAVING count(*) > 1 {offset_clause}
                ORDER BY document__tag.document_id
                LIMIT {batch_size}
                """
            )
        ).fetchall()
        if not batch:
            break
        doc_ids = [document_id for document_id, in batch]
        yield doc_ids
        offset_clause = f"AND document__tag.document_id > '{doc_ids[-1]}'"


def _get_vespa_metadata(
    document_id: str, index_name: str
) -> dict[str, str | list[str]]:
    url = DOCUMENT_ID_ENDPOINT.format(index_name=index_name)

    # Document-Selector language
    selection = (
        f"{index_name}.document_id=='{document_id}' and {index_name}.chunk_id==0"
    )

    params: dict[str, str | int] = {
        "selection": selection,
        "wantedDocumentCount": 1,
        "fieldSet": f"{index_name}:metadata",
    }

    with get_vespa_http_client() as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()

    docs = resp.json().get("documents", [])
    if not docs:
        raise RuntimeError(f"No chunk-0 found for document {document_id}")

    # for some reason, metadata is a string
    metadata = docs[0]["fields"]["metadata"]
    return json.loads(metadata)


def _get_document_tags(document_id: str) -> list[tuple[int, str, str]]:
    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            f"""
            SELECT tag.id, tag.tag_key, tag.tag_value
            FROM tag
            JOIN document__tag ON tag.id = document__tag.tag_id
            WHERE document__tag.document_id = '{document_id}'
            """
        )
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
