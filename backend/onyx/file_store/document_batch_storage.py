import json
from abc import ABC
from abc import abstractmethod
from enum import Enum
from io import StringIO
from typing import List
from typing import Optional
from typing import TypeAlias

from pydantic import BaseModel

from onyx.configs.constants import FileOrigin
from onyx.connectors.models import DocExtractionContext
from onyx.connectors.models import DocIndexingContext
from onyx.connectors.models import Document
from onyx.file_store.file_store import FileStore
from onyx.file_store.file_store import get_default_file_store
from onyx.utils.logger import setup_logger

logger = setup_logger()


class DocumentBatchStorageStateType(str, Enum):
    EXTRACTION = "extraction"
    INDEXING = "indexing"


DocumentStorageState: TypeAlias = DocExtractionContext | DocIndexingContext

STATE_TYPE_TO_MODEL: dict[str, type[DocumentStorageState]] = {
    DocumentBatchStorageStateType.EXTRACTION.value: DocExtractionContext,
    DocumentBatchStorageStateType.INDEXING.value: DocIndexingContext,
}


class BatchStoragePathInfo(BaseModel):
    cc_pair_id: int
    index_attempt_id: int
    batch_num: int


class DocumentBatchStorage(ABC):
    """Abstract base class for document batch storage implementations."""

    def __init__(self, cc_pair_id: int, index_attempt_id: int):
        self.cc_pair_id = cc_pair_id
        self.index_attempt_id = index_attempt_id
        self.base_path = f"{self._per_cc_pair_base_path()}/{index_attempt_id}"

    @abstractmethod
    def store_batch(self, batch_num: int, documents: List[Document]) -> None:
        """Store a batch of documents."""

    @abstractmethod
    def get_batch(self, batch_num: int) -> Optional[List[Document]]:
        """Retrieve a batch of documents."""

    @abstractmethod
    def delete_batch_by_name(self, batch_file_name: str) -> None:
        """Delete a specific batch."""

    @abstractmethod
    def delete_batch_by_num(self, batch_num: int) -> None:
        """Delete a specific batch."""

    @abstractmethod
    def cleanup_all_batches(self) -> None:
        """Clean up all batches and state for this index attempt."""

    @abstractmethod
    def get_all_batches_for_cc_pair(self) -> list[str]:
        """Get all IDs of batches stored in the file store."""

    @abstractmethod
    def update_old_batches_to_new_index_attempt(self, batch_names: list[str]) -> None:
        """Update all batches to the new index attempt."""
        """
        This is used when we need to re-issue docprocessing tasks for a new index attempt.
        We need to update the batch file names to the new index attempt ID.
        """

    @abstractmethod
    def extract_path_info(self, path: str) -> BatchStoragePathInfo | None:
        """Extract path info from a path."""

    def _serialize_documents(self, documents: list[Document]) -> str:
        """Serialize documents to JSON string."""
        # Use mode='json' to properly serialize datetime and other complex types
        return json.dumps([doc.model_dump(mode="json") for doc in documents], indent=2)

    def _deserialize_documents(self, data: str) -> list[Document]:
        """Deserialize documents from JSON string."""
        doc_dicts = json.loads(data)
        return [Document.model_validate(doc_dict) for doc_dict in doc_dicts]

    def _per_cc_pair_base_path(self) -> str:
        """Get the base path for the cc pair."""
        return f"iab/{self.cc_pair_id}"


class FileStoreDocumentBatchStorage(DocumentBatchStorage):
    """FileStore-based implementation of document batch storage."""

    def __init__(self, cc_pair_id: int, index_attempt_id: int, file_store: FileStore):
        super().__init__(cc_pair_id, index_attempt_id)
        self.file_store = file_store

    def _get_batch_file_name(self, batch_num: int) -> str:
        """Generate file name for a document batch."""
        return f"{self.base_path}/{batch_num}.json"

    def store_batch(self, batch_num: int, documents: list[Document]) -> None:
        """Store a batch of documents using FileStore."""
        file_name = self._get_batch_file_name(batch_num)
        try:
            data = self._serialize_documents(documents)
            content = StringIO(data)

            self.file_store.save_file(
                file_id=file_name,
                content=content,
                display_name=f"Document Batch {batch_num}",
                file_origin=FileOrigin.OTHER,
                file_type="application/json",
                file_metadata={
                    "batch_num": batch_num,
                    "document_count": str(len(documents)),
                },
            )

            logger.debug(
                f"Stored batch {batch_num} with {len(documents)} documents to FileStore as {file_name}"
            )
        except Exception as e:
            logger.error(f"Failed to store batch {batch_num}: {e}")
            raise

    def get_batch(self, batch_num: int) -> list[Document] | None:
        """Retrieve a batch of documents from FileStore."""
        file_name = self._get_batch_file_name(batch_num)
        try:
            # Check if file exists
            if not self.file_store.has_file(
                file_id=file_name,
                file_origin=FileOrigin.OTHER,
                file_type="application/json",
            ):
                logger.warning(
                    f"Batch {batch_num} not found in FileStore with name {file_name}"
                )
                return None

            content_io = self.file_store.read_file(file_name)
            data = content_io.read().decode("utf-8")

            documents = self._deserialize_documents(data)
            logger.debug(
                f"Retrieved batch {batch_num} with {len(documents)} documents from FileStore"
            )
            return documents
        except Exception as e:
            logger.error(f"Failed to retrieve batch {batch_num}: {e}")
            raise

    def delete_batch_by_name(self, batch_file_name: str) -> None:
        """Delete a specific batch from FileStore."""
        self.file_store.delete_file(batch_file_name)
        logger.debug(f"Deleted batch {batch_file_name} from FileStore")

    def delete_batch_by_num(self, batch_num: int) -> None:
        """Delete a specific batch from FileStore."""
        batch_file_name = self._get_batch_file_name(batch_num)
        self.delete_batch_by_name(batch_file_name)
        logger.debug(f"Deleted batch num {batch_num} {batch_file_name} from FileStore")

    def cleanup_all_batches(self) -> None:
        """Clean up all batches for this index attempt."""
        for batch_file_name in self.get_all_batches_for_cc_pair():
            self.delete_batch_by_name(batch_file_name)

    def get_all_batches_for_cc_pair(self) -> list[str]:
        """Get all IDs of batches stored in the file store for the cc pair
        this batch store was initialized with.
        This includes any batches left over from a previous
        indexing attempt that need to be processed.
        """
        return [
            file.file_id
            for file in self.file_store.list_files_by_prefix(
                self._per_cc_pair_base_path()
            )
        ]

    def update_old_batches_to_new_index_attempt(self, batch_names: list[str]) -> None:
        """Update all batches to the new index attempt."""
        for batch_file_name in batch_names:
            path_info = self.extract_path_info(batch_file_name)
            if path_info is None:
                logger.warning(
                    f"Could not extract path info from batch file: {batch_file_name}"
                )
                continue
            new_batch_file_name = self._get_batch_file_name(path_info.batch_num)
            self.file_store.change_file_id(batch_file_name, new_batch_file_name)

    def extract_path_info(self, path: str) -> BatchStoragePathInfo | None:
        """Extract path info from a path."""
        path_spl = path.split("/")
        # TODO: remove this in a few months, just for backwards compatibility
        if len(path_spl) == 3:
            path_spl = ["iab"] + path_spl
        try:
            _, cc_pair_id, index_attempt_id, batch_num = path_spl
            return BatchStoragePathInfo(
                cc_pair_id=int(cc_pair_id),
                index_attempt_id=int(index_attempt_id),
                batch_num=int(batch_num.split(".")[0]),  # remove .json
            )
        except Exception as e:
            logger.error(f"Failed to extract path info from {path}: {e}")
            return None


def get_document_batch_storage(
    cc_pair_id: int, index_attempt_id: int
) -> DocumentBatchStorage:
    """Factory function to get the configured document batch storage implementation."""
    # The get_default_file_store will now correctly use S3BackedFileStore
    # or other configured stores based on environment variables
    file_store = get_default_file_store()
    return FileStoreDocumentBatchStorage(cc_pair_id, index_attempt_id, file_store)
