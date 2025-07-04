"""drive-canonical-ids

Revision ID: 12635f6655b7
Revises: 58c50ef19f08
Create Date: 2025-06-20 14:44:54.241159

"""

from alembic import op
import sqlalchemy as sa
from urllib.parse import urlparse, urlunparse

from onyx.document_index.factory import get_default_document_index
from onyx.db.search_settings import SearchSettings
from onyx.document_index.vespa.shared_utils.utils import get_vespa_http_client
from onyx.document_index.vespa.shared_utils.utils import (
    replace_invalid_doc_id_characters,
)
from onyx.document_index.vespa_constants import SEARCH_ENDPOINT, DOCUMENT_ID_ENDPOINT
from onyx.utils.logger import setup_logger

logger = setup_logger()

# revision identifiers, used by Alembic.
revision = "12635f6655b7"
down_revision = "58c50ef19f08"
branch_labels = None
depends_on = None


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


def normalize_google_drive_url(url: str) -> str:
    """Remove query parameters from Google Drive URLs to create canonical document IDs.
    NOTE: copied from drive doc_conversion.py
    """
    parsed_url = urlparse(url)
    parsed_url = parsed_url._replace(query="")
    spl_path = parsed_url.path.split("/")
    if spl_path and (spl_path[-1] in ["edit", "view", "preview"]):
        spl_path.pop()
        parsed_url = parsed_url._replace(path="/".join(spl_path))
    # Remove query parameters and reconstruct URL
    return urlunparse(parsed_url)


def get_google_drive_documents_from_database() -> list[dict]:
    """Get all Google Drive documents from the database."""
    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            """
            SELECT d.id, cc.id as cc_pair_id
            FROM document d
            JOIN document_by_connector_credential_pair dcc ON d.id = dcc.id
            JOIN connector_credential_pair cc ON dcc.connector_id = cc.connector_id
                AND dcc.credential_id = cc.credential_id
            JOIN connector c ON cc.connector_id = c.id
            WHERE c.source = 'GOOGLE_DRIVE'
        """
        )
    )

    documents = []
    for row in result:
        documents.append({"document_id": row.id, "cc_pair_id": row.cc_pair_id})

    return documents


def update_document_id_in_database(old_doc_id: str, new_doc_id: str) -> None:
    """Update document IDs in all relevant database tables using copy-and-swap approach."""
    bind = op.get_bind()

    logger.info(f"Updating database tables for document {old_doc_id} -> {new_doc_id}")

    # Check if new document ID already exists
    result = bind.execute(
        sa.text("SELECT COUNT(*) FROM document WHERE id = :new_id"),
        {"new_id": new_doc_id},
    )
    row = result.fetchone()
    if row and row[0] > 0:
        raise RuntimeError(
            f"Document with ID {new_doc_id} already exists, cannot create duplicate"
        )

    # Step 1: Create a new document row with the new ID (copy all fields from old row)
    # Use a conservative approach to handle columns that might not exist in all installations
    try:
        bind.execute(
            sa.text(
                """
                INSERT INTO document (id, from_ingestion_api, boost, hidden, semantic_id,
                                    link, doc_updated_at, primary_owners, secondary_owners,
                                    external_user_emails, external_user_group_ids, is_public,
                                    chunk_count, last_modified, last_synced, kg_stage, kg_processing_time)
                SELECT :new_id, from_ingestion_api, boost, hidden, semantic_id,
                       link, doc_updated_at, primary_owners, secondary_owners,
                       external_user_emails, external_user_group_ids, is_public,
                       chunk_count, last_modified, last_synced, kg_stage, kg_processing_time
                FROM document
                WHERE id = :old_id
            """
            ),
            {"new_id": new_doc_id, "old_id": old_doc_id},
        )
    except Exception as e:
        # If the full INSERT fails, try a more basic version with only core columns
        logger.warning(f"Full INSERT failed, trying basic version: {e}")
        bind.execute(
            sa.text(
                """
                INSERT INTO document (id, from_ingestion_api, boost, hidden, semantic_id,
                                    link, doc_updated_at, primary_owners, secondary_owners)
                SELECT :new_id, from_ingestion_api, boost, hidden, semantic_id,
                       link, doc_updated_at, primary_owners, secondary_owners
                FROM document
                WHERE id = :old_id
            """
            ),
            {"new_id": new_doc_id, "old_id": old_doc_id},
        )

    # Step 2: Update all foreign key references to point to the new ID

    # Update document_by_connector_credential_pair table
    bind.execute(
        sa.text(
            "UPDATE document_by_connector_credential_pair SET id = :new_id WHERE id = :old_id"
        ),
        {"new_id": new_doc_id, "old_id": old_doc_id},
    )

    # Update search_doc table (stores search results for chat replay)
    bind.execute(
        sa.text(
            "UPDATE search_doc SET document_id = :new_id WHERE document_id = :old_id"
        ),
        {"new_id": new_doc_id, "old_id": old_doc_id},
    )

    # Update document_retrieval_feedback table (user feedback on documents)
    bind.execute(
        sa.text(
            "UPDATE document_retrieval_feedback SET document_id = :new_id WHERE document_id = :old_id"
        ),
        {"new_id": new_doc_id, "old_id": old_doc_id},
    )

    # Update document__tag table (document-tag relationships)
    bind.execute(
        sa.text(
            "UPDATE document__tag SET document_id = :new_id WHERE document_id = :old_id"
        ),
        {"new_id": new_doc_id, "old_id": old_doc_id},
    )

    # Update user_file table (user uploaded files linked to documents)
    bind.execute(
        sa.text(
            "UPDATE user_file SET document_id = :new_id WHERE document_id = :old_id"
        ),
        {"new_id": new_doc_id, "old_id": old_doc_id},
    )

    # Update KG and chunk_stats tables (these may not exist in all installations)
    try:
        # Update kg_entity table
        bind.execute(
            sa.text(
                "UPDATE kg_entity SET document_id = :new_id WHERE document_id = :old_id"
            ),
            {"new_id": new_doc_id, "old_id": old_doc_id},
        )

        # Update kg_entity_extraction_staging table
        bind.execute(
            sa.text(
                "UPDATE kg_entity_extraction_staging SET document_id = :new_id WHERE document_id = :old_id"
            ),
            {"new_id": new_doc_id, "old_id": old_doc_id},
        )

        # Update kg_relationship table
        bind.execute(
            sa.text(
                "UPDATE kg_relationship SET source_document = :new_id WHERE source_document = :old_id"
            ),
            {"new_id": new_doc_id, "old_id": old_doc_id},
        )

        # Update kg_relationship_extraction_staging table
        bind.execute(
            sa.text(
                "UPDATE kg_relationship_extraction_staging SET source_document = :new_id WHERE source_document = :old_id"
            ),
            {"new_id": new_doc_id, "old_id": old_doc_id},
        )

        # Update chunk_stats table
        bind.execute(
            sa.text(
                "UPDATE chunk_stats SET document_id = :new_id WHERE document_id = :old_id"
            ),
            {"new_id": new_doc_id, "old_id": old_doc_id},
        )

        # Update chunk_stats ID field which includes document_id
        bind.execute(
            sa.text(
                """
                UPDATE chunk_stats
                SET id = REPLACE(id, :old_id, :new_id)
                WHERE id LIKE :old_id_pattern
            """
            ),
            {
                "new_id": new_doc_id,
                "old_id": old_doc_id,
                "old_id_pattern": f"{old_doc_id}__%",
            },
        )

    except Exception as e:
        logger.warning(f"Some KG/chunk tables may not exist or failed to update: {e}")

    # Step 3: Delete the old document row (this should now be safe since all FKs point to new row)
    bind.execute(
        sa.text("DELETE FROM document WHERE id = :old_id"), {"old_id": old_doc_id}
    )


def delete_document_chunks_from_vespa(index_name: str, doc_id: str) -> None:
    """Delete all chunks for a document from Vespa using pagination."""
    offset = 0
    limit = 400  # Vespa's maximum hits per query
    total_deleted = 0

    with get_vespa_http_client() as http_client:
        while True:
            # Use pagination to handle the 400 hit limit
            yql = f'select documentid, document_id, chunk_id from sources {index_name} where document_id contains "{doc_id}"'

            params = {
                "yql": yql,
                "hits": str(limit),
                "offset": str(offset),
                "timeout": "30s",
                "format": "json",
            }

            response = http_client.get(SEARCH_ENDPOINT, params=params, timeout=None)
            response.raise_for_status()

            search_result = response.json()
            hits = search_result.get("root", {}).get("children", [])

            if not hits:
                break  # No more chunks to process

            # Delete each chunk in this batch
            for hit in hits:
                vespa_doc_id = hit.get("id")  # This is the internal Vespa document ID
                if not vespa_doc_id:
                    print(f"No Vespa document ID found for chunk {hit}")
                    continue
                vespa_doc_id = vespa_doc_id.split("::")[-1]  # get the UUID from the end

                # Delete the chunk using the internal Vespa document ID
                delete_url = f"{DOCUMENT_ID_ENDPOINT.format(index_name=index_name)}/{vespa_doc_id}"

                try:
                    resp = http_client.delete(delete_url)
                    resp.raise_for_status()
                    total_deleted += 1
                except Exception as e:
                    print(f"Failed to delete chunk {vespa_doc_id}: {e}")
                    # Continue trying to delete other chunks even if one fails
                    continue

            # Move to next batch
            offset += limit

            # If we got fewer hits than the limit, we're done
            if len(hits) < limit:
                break


def update_document_id_in_vespa(
    index_name: str, old_doc_id: str, new_doc_id: str
) -> None:
    """Update a document's ID in Vespa by updating the document_id field."""
    # Clean the new document ID for storage in Vespa (this handles invalid characters)
    clean_new_doc_id = replace_invalid_doc_id_characters(new_doc_id)

    offset = 0
    limit = 400  # Vespa's maximum hits per query
    total_updated = 0

    with get_vespa_http_client() as http_client:
        while True:
            # Use pagination to handle the 400 hit limit
            yql = f'select documentid, document_id, chunk_id from sources {index_name} where document_id contains "{old_doc_id}"'

            params = {
                "yql": yql,
                "hits": str(limit),
                "offset": str(offset),
                "timeout": "30s",
                "format": "json",
            }

            response = http_client.get(SEARCH_ENDPOINT, params=params, timeout=None)
            response.raise_for_status()

            search_result = response.json()
            hits = search_result.get("root", {}).get("children", [])

            if not hits:
                break  # No more chunks to process

            # Update each chunk in this batch
            for hit in hits:
                vespa_doc_id = hit.get("id")  # This is the internal Vespa document ID
                if not vespa_doc_id:
                    print(f"No Vespa document ID found for chunk {hit}")
                    continue
                vespa_doc_id = vespa_doc_id.split("::")[-1]  # get the UUID from the end

                vespa_url = f"{DOCUMENT_ID_ENDPOINT.format(index_name=index_name)}/{vespa_doc_id}"
                update_request = {
                    "fields": {"document_id": {"assign": clean_new_doc_id}}
                }

                try:
                    resp = http_client.put(vespa_url, json=update_request)
                    resp.raise_for_status()
                    total_updated += 1
                except Exception as e:
                    print(f"Failed to update chunk {vespa_doc_id}: {e}")
                    raise

            # Move to next batch
            offset += limit

            # If we got fewer hits than the limit, we're done
            if len(hits) < limit:
                break


def delete_document_from_db(current_doc_id: str, index_name: str) -> None:
    # Delete all foreign key references first, then delete the document
    try:
        bind = op.get_bind()

        # Delete from document_by_connector_credential_pair
        bind.execute(
            sa.text(
                "DELETE FROM document_by_connector_credential_pair WHERE id = :doc_id"
            ),
            {"doc_id": current_doc_id},
        )

        # Delete from other tables that reference this document
        bind.execute(
            sa.text("DELETE FROM search_doc WHERE document_id = :doc_id"),
            {"doc_id": current_doc_id},
        )

        bind.execute(
            sa.text(
                "DELETE FROM document_retrieval_feedback WHERE document_id = :doc_id"
            ),
            {"doc_id": current_doc_id},
        )

        bind.execute(
            sa.text("DELETE FROM document__tag WHERE document_id = :doc_id"),
            {"doc_id": current_doc_id},
        )

        bind.execute(
            sa.text("DELETE FROM user_file WHERE document_id = :doc_id"),
            {"doc_id": current_doc_id},
        )

        # Delete from KG tables if they exist
        try:
            bind.execute(
                sa.text("DELETE FROM kg_entity WHERE document_id = :doc_id"),
                {"doc_id": current_doc_id},
            )

            bind.execute(
                sa.text(
                    "DELETE FROM kg_entity_extraction_staging WHERE document_id = :doc_id"
                ),
                {"doc_id": current_doc_id},
            )

            bind.execute(
                sa.text("DELETE FROM kg_relationship WHERE source_document = :doc_id"),
                {"doc_id": current_doc_id},
            )

            bind.execute(
                sa.text(
                    "DELETE FROM kg_relationship_extraction_staging WHERE source_document = :doc_id"
                ),
                {"doc_id": current_doc_id},
            )

            bind.execute(
                sa.text("DELETE FROM chunk_stats WHERE document_id = :doc_id"),
                {"doc_id": current_doc_id},
            )

            bind.execute(
                sa.text("DELETE FROM chunk_stats WHERE id LIKE :doc_id_pattern"),
                {"doc_id_pattern": f"{current_doc_id}__%"},
            )

        except Exception as e:
            logger.warning(
                f"Some KG/chunk tables may not exist or failed to delete from: {e}"
            )

        # Finally delete the document itself
        bind.execute(
            sa.text("DELETE FROM document WHERE id = :doc_id"),
            {"doc_id": current_doc_id},
        )

        # Delete chunks from vespa
        delete_document_chunks_from_vespa(index_name, current_doc_id)

    except Exception as e:
        print(f"Failed to delete duplicate document {current_doc_id}: {e}")
        # Continue with other documents instead of failing the entire migration


def upgrade() -> None:
    current_search_settings, future_search_settings = active_search_settings()
    document_index = get_default_document_index(
        current_search_settings,
        future_search_settings,
    )

    # Get the index name
    if hasattr(document_index, "index_name"):
        index_name = document_index.index_name
    else:
        # Default index name if we can't get it from the document_index
        index_name = "danswer_index"

    # Get all Google Drive documents from the database (this is faster and more reliable)
    gdrive_documents = get_google_drive_documents_from_database()

    if not gdrive_documents:
        return

    # Track normalized document IDs to detect duplicates
    all_normalized_doc_ids = set()
    updated_count = 0

    for doc_info in gdrive_documents:
        current_doc_id = doc_info["document_id"]
        normalized_doc_id = normalize_google_drive_url(current_doc_id)

        # Check for duplicates
        if normalized_doc_id in all_normalized_doc_ids:
            delete_document_from_db(current_doc_id, index_name)
            continue

        all_normalized_doc_ids.add(normalized_doc_id)

        # If the document ID already doesn't have query parameters, skip it
        if current_doc_id == normalized_doc_id:
            continue

        try:
            # Update both database and Vespa in order
            # Database first to ensure consistency
            update_document_id_in_database(current_doc_id, normalized_doc_id)

            # For Vespa, we can now use the original document IDs since we're using contains matching
            update_document_id_in_vespa(index_name, current_doc_id, normalized_doc_id)
            updated_count += 1
        except Exception as e:
            print(f"Failed to update document {current_doc_id}: {e}")
            from httpx import HTTPStatusError

            if isinstance(e, HTTPStatusError):
                print(f"HTTPStatusError: {e}")
                print(f"Response: {e.response.text}")
                print(f"Status: {e.response.status_code}")
                print(f"Headers: {e.response.headers}")
                print(f"Request: {e.request.url}")
                print(f"Request headers: {e.request.headers}")
            # Note: Rollback is complex with copy-and-swap approach since the old document is already deleted
            # In case of failure, manual intervention may be required
            # Continue with other documents instead of failing the entire migration
            continue

    logger.info(f"Migration complete. Updated {updated_count} Google Drive documents")


def downgrade() -> None:
    # this is a one way migration, so no downgrade.
    # It wouldn't make sense to store the extra query parameters
    # and duplicate documents to allow a reversal.
    pass
