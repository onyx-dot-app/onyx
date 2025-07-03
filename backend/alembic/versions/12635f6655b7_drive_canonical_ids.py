"""drive-canonical-ids

Revision ID: 12635f6655b7
Revises: 03bf8be6b53a
Create Date: 2025-06-20 14:44:54.241159

"""

from alembic import op
import sqlalchemy as sa
from urllib.parse import urlparse, urlunparse

from onyx.document_index.factory import get_default_document_index
from onyx.db.search_settings import SearchSettings
from onyx.document_index.vespa.shared_utils.utils import get_vespa_http_client
from onyx.document_index.vespa_constants import SEARCH_ENDPOINT, DOCUMENT_ID_ENDPOINT
from onyx.utils.logger import setup_logger

logger = setup_logger()

# revision identifiers, used by Alembic.
revision = "12635f6655b7"
down_revision = "03bf8be6b53a"
branch_labels = None
depends_on = None


def active_search_settings() -> tuple[SearchSettings, SearchSettings]:
    result = op.get_bind().execute(
        sa.text(
            """
        SELECT * FROM search_settings WHERE status = 'PRESENT' ORDER BY id DESC LIMIT 1
        """
        )
    )
    search_settings = result.scalars().fetchall()[0]
    result2 = op.get_bind().execute(
        sa.text(
            """
        SELECT * FROM search_settings WHERE status = 'FUTURE' ORDER BY id DESC LIMIT 1
        """
        )
    )
    search_settings_future = result2.scalars().fetchall()[0]

    if not isinstance(search_settings, SearchSettings):
        raise RuntimeError(
            "current search settings is of type " + type(search_settings)
        )
    if not isinstance(search_settings_future, SearchSettings):
        raise RuntimeError(
            "future search settings is of type " + type(search_settings_future)
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
    """Query the database to get all Google Drive documents with their current document IDs."""
    # Get all documents with source = 'google_drive' and have query parameters in their IDs
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
            WHERE c.source = 'google_drive' 
            AND d.id LIKE '%?%'
        """
        )
    )

    documents = []
    for row in result:
        documents.append({"document_id": row.id, "cc_pair_id": row.cc_pair_id})

    logger.info(
        f"Found {len(documents)} Google Drive documents with query parameters in database"
    )
    return documents


def update_document_id_in_database(old_doc_id: str, new_doc_id: str) -> None:
    """Update document IDs in all relevant database tables."""
    bind = op.get_bind()

    logger.info(f"Updating database tables for document {old_doc_id} -> {new_doc_id}")

    # Update the main document table
    bind.execute(
        sa.text("UPDATE document SET id = :new_id WHERE id = :old_id"),
        {"new_id": new_doc_id, "old_id": old_doc_id},
    )

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

    # Update knowledge graph tables if they exist and have references
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


def delete_document_chunks_from_vespa(index_name: str, doc_id: str) -> None:
    """Delete all chunks for a document from Vespa."""
    # Get all chunks for this document
    yql = f'select documentid, document_id, chunk_id from sources {index_name} where document_id contains "{doc_id}"'

    params = {
        "yql": yql,
        "hits": "10000",  # Get all chunks for this document
        "timeout": "30s",
        "format": "json",
    }

    with get_vespa_http_client() as http_client:
        response = http_client.get(SEARCH_ENDPOINT, params=params, timeout=None)
        response.raise_for_status()

        search_result = response.json()
        hits = search_result.get("root", {}).get("children", [])

        logger.info(f"Deleting {len(hits)} chunks for duplicate document {doc_id}")

        # Delete each chunk
        for hit in hits:
            vespa_doc_id = hit.get("id")  # This is the internal Vespa document ID
            if not vespa_doc_id:
                logger.warning(f"No Vespa document ID found for chunk {hit}")
                continue

            # Delete the chunk
            delete_url = (
                f"{DOCUMENT_ID_ENDPOINT.format(index_name=index_name)}/{vespa_doc_id}"
            )

            try:
                resp = http_client.delete(delete_url)
                resp.raise_for_status()
            except Exception as e:
                logger.error(f"Failed to delete chunk {vespa_doc_id}: {e}")
                # Continue trying to delete other chunks even if one fails
                continue


def update_document_id_in_vespa(
    index_name: str, old_doc_id: str, new_doc_id: str
) -> None:
    """Update a document's ID in Vespa by copying it with the new ID and deleting the old one."""
    # Note: In Vespa, we can't directly change a document's ID.
    # We would need to re-index the document with the new ID.
    # For this migration, we'll use the update API to modify the document_id field.

    # Get all chunks for this document
    yql = f'select documentid, document_id, chunk_id from sources {index_name} where document_id contains "{old_doc_id}"'

    params = {
        "yql": yql,
        "hits": "10000",  # Get all chunks for this document
        "timeout": "30s",
        "format": "json",
    }

    with get_vespa_http_client() as http_client:
        response = http_client.get(SEARCH_ENDPOINT, params=params, timeout=None)
        response.raise_for_status()

        search_result = response.json()
        hits = search_result.get("root", {}).get("children", [])

        logger.info(
            f"Updating {len(hits)} chunks for document {old_doc_id} -> {new_doc_id}"
        )

        # Update each chunk
        for hit in hits:
            vespa_doc_id = hit.get("id")  # This is the internal Vespa document ID
            if not vespa_doc_id:
                logger.warning(f"No Vespa document ID found for chunk {hit}")
                continue
            # Update the document_id field
            update_dict = {"fields": {"document_id": {"assign": new_doc_id}}}

            vespa_url = (
                f"{DOCUMENT_ID_ENDPOINT.format(index_name=index_name)}/{vespa_doc_id}"
            )

            try:
                resp = http_client.put(
                    vespa_url,
                    headers={"Content-Type": "application/json"},
                    json=update_dict,
                )
                resp.raise_for_status()
            except Exception as e:
                logger.error(f"Failed to update chunk {vespa_doc_id}: {e}")
                raise


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

    logger.info(f"Starting Google Drive document ID migration for index: {index_name}")

    # Get all Google Drive documents from the database (this is faster and more reliable)
    gdrive_documents = get_google_drive_documents_from_database()

    if not gdrive_documents:
        logger.info(
            "No Google Drive documents with query parameters found, migration complete"
        )
        return

    all_normalized_doc_ids = set()

    # Process each document
    updated_count = 0
    for doc in gdrive_documents:
        current_doc_id = doc["document_id"]

        # Normalize the document ID (remove query parameters)
        normalized_doc_id = normalize_google_drive_url(current_doc_id)
        if normalized_doc_id in all_normalized_doc_ids:
            # delete second instance of the document in the database
            bind = op.get_bind()
            bind.execute(
                sa.text("DELETE FROM document WHERE id = :doc_id"),
                {"doc_id": current_doc_id},
            )
            # delete chunks from vespa
            delete_document_chunks_from_vespa(index_name, current_doc_id)
            continue
        all_normalized_doc_ids.add(normalized_doc_id)

        # If the document ID already doesn't have query parameters, skip it
        if current_doc_id == normalized_doc_id:
            continue

        logger.info(f"Updating document ID: {current_doc_id} -> {normalized_doc_id}")

        try:
            # Update both database and Vespa in order
            # Database first to ensure consistency
            update_document_id_in_database(current_doc_id, normalized_doc_id)
            update_document_id_in_vespa(index_name, current_doc_id, normalized_doc_id)
            updated_count += 1
        except Exception as e:
            logger.error(f"Failed to update document {current_doc_id}: {e}")
            # Rollback database changes if Vespa update fails
            try:
                update_document_id_in_database(normalized_doc_id, current_doc_id)
            except Exception as rollback_error:
                logger.error(
                    f"Failed to rollback database changes for {current_doc_id}: {rollback_error}"
                )
            # Continue with other documents instead of failing the entire migration
            continue

    logger.info(f"Migration complete. Updated {updated_count} Google Drive documents")


def downgrade() -> None:
    # this is a one way migration, so no downgrade.
    # It wouldn't make sense to store the extra query parameters
    # and duplicate documents to allow a reversal.
    pass
