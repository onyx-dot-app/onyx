import os
import sys

from sqlalchemy import text
from sqlalchemy.orm import Session

# makes it so `PYTHONPATH=.` is not required when running this script
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)

from onyx.db.engine import get_session_context_manager  # noqa: E402
from onyx.db.document import delete_documents_complete__no_commit  # noqa: E402
from onyx.db.search_settings import get_current_search_settings  # noqa: E402
from onyx.document_index.vespa.index import VespaIndex  # noqa: E402
from onyx.background.celery.tasks.shared.RetryDocumentIndex import (  # noqa: E402
    RetryDocumentIndex,
)


def _get_orphaned_document_ids(db_session: Session) -> list[str]:
    """Get document IDs that don't have any entries in document_by_connector_credential_pair"""
    query = text(
        """
        SELECT d.id
        FROM document d
        LEFT JOIN document_by_connector_credential_pair dbcc ON d.id = dbcc.id
        WHERE dbcc.id IS NULL
    """
    )
    orphaned_ids = [doc_id[0] for doc_id in db_session.execute(query)]
    print(f"Found {len(orphaned_ids)} orphaned documents")
    return orphaned_ids


def main() -> None:
    with get_session_context_manager() as db_session:
        # Get orphaned document IDs
        orphaned_ids = _get_orphaned_document_ids(db_session)
        if not orphaned_ids:
            print("No orphaned documents found")
            return

        # Setup Vespa index
        search_settings = get_current_search_settings(db_session)
        index_name = search_settings.index_name
        vespa_index = VespaIndex(index_name=index_name, secondary_index_name=None)
        retry_index = RetryDocumentIndex(vespa_index)

        # Delete chunks from Vespa first
        print("Deleting orphaned document chunks from Vespa")
        successfully_vespa_deleted_doc_ids = []
        for doc_id in orphaned_ids:
            try:
                chunks_deleted = retry_index.delete_single(doc_id)
                successfully_vespa_deleted_doc_ids.append(doc_id)
                if chunks_deleted > 0:
                    print(f"Deleted {chunks_deleted} chunks for document {doc_id}")
            except Exception as e:
                print(
                    f"Error deleting document {doc_id} in Vespa and will not delete from Postgres: {e}"
                )

        # Delete documents from Postgres
        print("Deleting orphaned documents from Postgres")
        try:
            delete_documents_complete__no_commit(
                db_session, successfully_vespa_deleted_doc_ids
            )
            db_session.commit()
        except Exception as e:
            print(f"Error deleting documents from Postgres: {e}")

    print(
        f"Successfully cleaned up {len(successfully_vespa_deleted_doc_ids)} orphaned documents"
    )


if __name__ == "__main__":
    main()
