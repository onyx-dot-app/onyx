import concurrent.futures
import os
import sys

from sqlalchemy import text
from sqlalchemy.orm import Session

from onyx.document_index.document_index_utils import get_multipass_config
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA

# makes it so `PYTHONPATH=.` is not required when running this script
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)

from onyx.context.search.models import IndexFilters  # noqa: E402
from onyx.document_index.interfaces import VespaChunkRequest  # noqa: E402
from onyx.db.engine.sql_engine import get_session_with_current_tenant  # noqa: E402
from onyx.db.document import delete_documents_complete__no_commit  # noqa: E402
from onyx.db.tag import delete_orphan_tags__no_commit  # noqa: E402
from onyx.db.search_settings import get_current_search_settings  # noqa: E402
from onyx.document_index.vespa.index import VespaIndex  # noqa: E402
from onyx.db.document import get_document  # noqa: E402

BATCH_SIZE = 100


def _get_orphaned_document_ids(db_session: Session, limit: int) -> list[str]:
    """Get document IDs that don't have any entries in document_by_connector_credential_pair"""
    query = text(
        """
        SELECT d.id
        FROM document d
        LEFT JOIN document_by_connector_credential_pair dbcc ON d.id = dbcc.id
        WHERE dbcc.id IS NULL
        LIMIT :limit
    """
    )
    orphaned_ids = [doc_id[0] for doc_id in db_session.execute(query, {"limit": limit})]
    print(f"Found {len(orphaned_ids)} orphaned documents in this batch")
    return orphaned_ids


def main() -> None:
    with get_session_with_current_tenant() as db_session:
        total_processed = 0
        while True:
            # Get orphaned document IDs in batches
            orphaned_ids = _get_orphaned_document_ids(db_session, BATCH_SIZE)
            if not orphaned_ids:
                if total_processed == 0:
                    print("No orphaned documents found")
                else:
                    print(
                        f"Finished processing all batches. Total documents "
                        f"processed: {total_processed}"
                    )
                return

            # Setup Vespa index
            search_settings = get_current_search_settings(db_session)
            multipass_config = get_multipass_config(search_settings)
            index_name = search_settings.index_name
            vespa_index = VespaIndex(
                index_name=index_name,
                secondary_index_name=None,
                large_chunks_enabled=multipass_config.enable_large_chunks,
                secondary_large_chunks_enabled=None,
            )

            # Delete chunks from Vespa first
            print("Deleting orphaned document chunks from Vespa")
            successfully_vespa_deleted_doc_ids: list[str] = []
            # Process documents in parallel using ThreadPoolExecutor
            with concurrent.futures.ThreadPoolExecutor(max_workers=100) as executor:

                def process_doc(doc_id: str) -> str | None:
                    document = get_document(doc_id, db_session)
                    if not document:
                        return None
                    # Check if document exists in Vespa first
                    try:
                        chunks = vespa_index.id_based_retrieval(
                            chunk_requests=[
                                VespaChunkRequest(document_id=doc_id, max_chunk_ind=2)
                            ],
                            filters=IndexFilters(access_control_list=None),
                            batch_retrieval=True,
                        )
                        if not chunks:
                            print(f"Document {doc_id} not found in Vespa")
                            return doc_id
                    except Exception as e:
                        print(
                            f"Error checking if document {doc_id} exists in Vespa: {e}"
                        )
                        return None

                    try:
                        print(f"Deleting document {doc_id} in Vespa")
                        chunks_deleted = vespa_index.delete_single(
                            doc_id,
                            tenant_id=POSTGRES_DEFAULT_SCHEMA,
                            chunk_count=document.chunk_count,
                        )
                        if chunks_deleted > 0:
                            print(
                                f"Deleted {chunks_deleted} chunks for document {doc_id}"
                            )
                        return doc_id
                    except Exception as e:
                        print(
                            f"Error deleting document {doc_id} in Vespa and "
                            f"will not delete from Postgres: {e}"
                        )
                        return None

                # Submit all tasks and gather results
                futures = [
                    executor.submit(process_doc, doc_id) for doc_id in orphaned_ids
                ]
                for future in concurrent.futures.as_completed(futures):
                    doc_id = future.result()
                    if doc_id:
                        successfully_vespa_deleted_doc_ids.append(doc_id)

            # Delete documents from Postgres
            print("Deleting orphaned documents from Postgres")
            try:
                delete_documents_complete__no_commit(
                    db_session, successfully_vespa_deleted_doc_ids
                )
                delete_orphan_tags__no_commit(db_session)
                db_session.commit()
            except Exception as e:
                print(f"Error deleting documents from Postgres: {e}")
                break

            total_processed += len(successfully_vespa_deleted_doc_ids)
            print(
                f"Successfully cleaned up {len(successfully_vespa_deleted_doc_ids)}"
                f" orphaned documents in this batch"
            )
            print(f"Total documents processed so far: {total_processed}")


if __name__ == "__main__":
    main()
