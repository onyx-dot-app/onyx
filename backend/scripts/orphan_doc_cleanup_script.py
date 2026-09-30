import concurrent.futures
import os
import sys

from sqlalchemy import text
from sqlalchemy.orm import Session

# makes it so `PYTHONPATH=.` is not required when running this script
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)

from onyx.context.search.models import IndexFilters  # noqa: E402
from onyx.db.document import (  # noqa: E402
    delete_documents_complete__no_commit,
    get_document,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant  # noqa: E402
from onyx.db.search_settings import get_current_search_settings  # noqa: E402
from onyx.db.tag import delete_orphan_tags_batched  # noqa: E402
from onyx.document_index.factory import get_default_document_index  # noqa: E402
from onyx.document_index.interfaces_new import (  # noqa: E402
    DocumentIndex,
    DocumentSectionRequest,
)

BATCH_SIZE = 100


def _get_orphaned_document_ids(db_session: Session, limit: int) -> list[str]:
    """Get document IDs that don't have any entries in document_by_connector_credential_pair"""
    query = text("""
        SELECT d.id
        FROM document d
        LEFT JOIN document_by_connector_credential_pair dbcc ON d.id = dbcc.id
        WHERE dbcc.id IS NULL
        LIMIT :limit
    """)
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
                        f"Finished processing all batches. Total documents processed: {total_processed}"
                    )
                return

            search_settings = get_current_search_settings(db_session)
            document_index = get_default_document_index(search_settings, None)

            # Delete chunks from the document index first
            print("Deleting orphaned document chunks from the document index")
            successfully_index_deleted_doc_ids: list[str] = []
            # Process documents in parallel using ThreadPoolExecutor
            with concurrent.futures.ThreadPoolExecutor(max_workers=100) as executor:

                def process_doc(
                    doc_id: str, document_index: DocumentIndex = document_index
                ) -> str | None:
                    document = get_document(doc_id, db_session)
                    if not document:
                        return None
                    # Check if document exists in the document index first
                    try:
                        chunks = document_index.id_based_retrieval(
                            chunk_requests=[
                                DocumentSectionRequest(
                                    document_id=doc_id, max_chunk_ind=2
                                )
                            ],
                            filters=IndexFilters(access_control_list=None),
                            batch_retrieval=True,
                        )
                        if not chunks:
                            print(f"Document {doc_id} not found in the document index")
                            return doc_id
                    except Exception as e:
                        print(
                            f"Error checking if document {doc_id} exists in the document index: {e}"
                        )
                        return None

                    try:
                        print(f"Deleting document {doc_id} in the document index")
                        chunks_deleted = document_index.delete(
                            doc_id,
                            chunk_count=document.chunk_count,
                        )
                        if chunks_deleted > 0:
                            print(
                                f"Deleted {chunks_deleted} chunks for document {doc_id}"
                            )
                        return doc_id
                    except Exception as e:
                        print(
                            f"Error deleting document {doc_id} in the document index and will not delete from Postgres: {e}"
                        )
                        return None

                # Submit all tasks and gather results
                futures = [
                    executor.submit(process_doc, doc_id) for doc_id in orphaned_ids
                ]
                for future in concurrent.futures.as_completed(futures):
                    doc_id = future.result()
                    if doc_id:
                        successfully_index_deleted_doc_ids.append(doc_id)

            # Delete documents from Postgres
            print("Deleting orphaned documents from Postgres")
            try:
                delete_documents_complete__no_commit(
                    db_session, successfully_index_deleted_doc_ids
                )
                db_session.commit()
                delete_orphan_tags_batched(db_session)
            except Exception as e:
                print(f"Error deleting documents from Postgres: {e}")
                break

            total_processed += len(successfully_index_deleted_doc_ids)
            print(
                f"Successfully cleaned up {len(successfully_index_deleted_doc_ids)} orphaned documents in this batch"
            )
            print(f"Total documents processed so far: {total_processed}")


if __name__ == "__main__":
    main()
