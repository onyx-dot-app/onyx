import json
from abc import ABC
from abc import abstractmethod
from io import StringIO
from typing import List
from typing import Optional

from sqlalchemy.orm import Session

from onyx.background.indexing.run_indexing import RunIndexingContext
from onyx.configs.constants import FileOrigin
from onyx.connectors.models import Document
from onyx.file_store.file_store import FileStore
from onyx.file_store.file_store import get_default_file_store
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


class DocumentBatchStorage(ABC):
    """Abstract base class for document batch storage implementations."""

    def __init__(self, tenant_id: str, index_attempt_id: int):
        self.tenant_id = tenant_id
        self.index_attempt_id = index_attempt_id
        self.base_path = f"{tenant_id}/{index_attempt_id}"

    @abstractmethod
    def store_batch(self, batch_id: str, documents: List[Document]) -> None:
        """Store a batch of documents."""

    @abstractmethod
    def get_batch(self, batch_id: str) -> Optional[List[Document]]:
        """Retrieve a batch of documents."""

    @abstractmethod
    def delete_batch(self, batch_id: str) -> None:
        """Delete a specific batch."""

    @abstractmethod
    def store_extraction_state(self, state: RunIndexingContext) -> None:
        """Store extraction state metadata."""

    @abstractmethod
    def get_extraction_state(self) -> RunIndexingContext | None:
        """Get extraction state metadata."""

    @abstractmethod
    def cleanup_all_batches(self) -> None:
        """Clean up all batches and state for this index attempt."""

    def _serialize_documents(self, documents: list[Document]) -> str:
        """Serialize documents to JSON string."""
        # Use mode='json' to properly serialize datetime and other complex types
        return json.dumps([doc.model_dump(mode="json") for doc in documents], indent=2)

    def _deserialize_documents(self, data: str) -> list[Document]:
        """Deserialize documents from JSON string."""
        doc_dicts = json.loads(data)
        return [Document.model_validate(doc_dict) for doc_dict in doc_dicts]


class FileStoreDocumentBatchStorage(DocumentBatchStorage):
    """FileStore-based implementation of document batch storage."""

    def __init__(self, tenant_id: str, index_attempt_id: int, file_store: FileStore):
        super().__init__(tenant_id, index_attempt_id)
        self.file_store = file_store
        # Track stored batch files for cleanup
        self._batch_files: set[str] = set()

    def _get_batch_file_name(self, batch_id: str) -> str:
        """Generate file name for a document batch."""
        return f"document_batch_{self.base_path.replace('/', '_')}_{batch_id}.json"

    def _get_state_file_name(self) -> str:
        """Generate file name for extraction state."""
        return f"extraction_state_{self.base_path.replace('/', '_')}.json"

    def store_batch(self, batch_id: str, documents: list[Document]) -> None:
        """Store a batch of documents using FileStore."""
        file_name = self._get_batch_file_name(batch_id)
        try:
            data = self._serialize_documents(documents)
            content = StringIO(data)

            self.file_store.save_file(
                file_id=file_name,
                content=content,
                display_name=f"Document Batch {batch_id}",
                file_origin=FileOrigin.OTHER,
                file_type="application/json",
                file_metadata={
                    "tenant_id": self.tenant_id,
                    "index_attempt_id": str(self.index_attempt_id),
                    "batch_id": batch_id,
                    "document_count": str(len(documents)),
                },
            )

            # Track this batch file for cleanup
            self._batch_files.add(file_name)

            logger.debug(
                f"Stored batch {batch_id} with {len(documents)} documents to FileStore as {file_name}"
            )
        except Exception as e:
            logger.error(f"Failed to store batch {batch_id}: {e}")
            raise

    def get_batch(self, batch_id: str) -> list[Document] | None:
        """Retrieve a batch of documents from FileStore."""
        file_name = self._get_batch_file_name(batch_id)
        try:
            # Check if file exists
            if not self.file_store.has_file(
                file_id=file_name,
                file_origin=FileOrigin.OTHER,
                file_type="application/json",
            ):
                logger.warning(f"Batch {batch_id} not found in FileStore")
                return None

            content_io = self.file_store.read_file(file_name)
            data = content_io.read().decode("utf-8")

            documents = self._deserialize_documents(data)
            logger.debug(
                f"Retrieved batch {batch_id} with {len(documents)} documents from FileStore"
            )
            return documents
        except Exception as e:
            logger.error(f"Failed to retrieve batch {batch_id}: {e}")
            raise

    def delete_batch(self, batch_id: str) -> None:
        """Delete a specific batch from FileStore."""
        file_name = self._get_batch_file_name(batch_id)
        try:
            self.file_store.delete_file(file_name)
            # Remove from tracked files
            self._batch_files.discard(file_name)
            logger.debug(f"Deleted batch {batch_id} from FileStore")
        except Exception as e:
            logger.warning(f"Failed to delete batch {batch_id}: {e}")
            # Don't raise - batch might not exist, which is acceptable

    def store_extraction_state(self, state: RunIndexingContext) -> None:
        """Store extraction state using FileStore."""
        file_name = self._get_state_file_name()
        try:
            data = json.dumps(state.model_dump(mode="json"), indent=2)
            content = StringIO(data)

            self.file_store.save_file(
                file_id=file_name,
                content=content,
                display_name=f"Extraction State {self.base_path}",
                file_origin=FileOrigin.OTHER,
                file_type="application/json",
                file_metadata={
                    "tenant_id": self.tenant_id,
                    "index_attempt_id": str(self.index_attempt_id),
                    "type": "extraction_state",
                },
            )

            logger.debug(f"Stored extraction state to FileStore as {file_name}")
        except Exception as e:
            logger.error(f"Failed to store extraction state: {e}")
            raise

    def get_extraction_state(self) -> RunIndexingContext | None:
        """Get extraction state from FileStore."""
        file_name = self._get_state_file_name()
        try:
            # Check if file exists
            if not self.file_store.has_file(
                file_id=file_name,
                file_origin=FileOrigin.OTHER,
                file_type="application/json",
            ):
                return None

            content_io = self.file_store.read_file(file_name)
            data = content_io.read().decode("utf-8")

            state = RunIndexingContext.model_validate(json.loads(data))
            logger.debug("Retrieved extraction state from FileStore")
            return state
        except Exception as e:
            logger.error(f"Failed to retrieve extraction state: {e}")
            return None

    def cleanup_all_batches(self) -> None:
        """Clean up all batches and state for this index attempt."""
        # Since we don't have direct access to S3 listing logic here,
        # we'll rely on deleting tracked files.
        # A more robust cleanup might involve a separate task that can list/delete
        # from S3 if needed, but for now this is simpler.
        deleted_count = 0

        # Create a copy of the set to avoid issues with modification during iteration
        for file_name in list(self._batch_files):
            try:
                self.file_store.delete_file(file_name)
                deleted_count += 1
            except Exception as e:
                logger.warning(f"Failed to delete batch file {file_name}: {e}")

        # Delete extraction state
        try:
            state_file_name = self._get_state_file_name()
            self.file_store.delete_file(state_file_name)
            deleted_count += 1
        except Exception as e:
            logger.warning(f"Failed to delete extraction state: {e}")

        # Clear tracked files
        self._batch_files.clear()

        logger.info(
            f"Cleaned up {deleted_count} files for index attempt {self.index_attempt_id}"
        )


def get_document_batch_storage(
    tenant_id: str, index_attempt_id: int, db_session: Session
) -> DocumentBatchStorage:
    """Factory function to get the configured document batch storage implementation."""
    # Set tenant ID for the file store
    get_current_tenant_id(tenant_id)
    # The get_default_file_store will now correctly use S3BackedFileStore
    # or other configured stores based on environment variables
    file_store = get_default_file_store(db_session)
    return FileStoreDocumentBatchStorage(tenant_id, index_attempt_id, file_store)
