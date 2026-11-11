import json
from abc import ABC, abstractmethod
from collections.abc import Callable
from enum import Enum
from io import StringIO
from typing import List, Optional, TypeAlias, TypeVar

from pydantic import BaseModel

from onyx.configs.constants import FileOrigin
from onyx.connectors.models import (
    DocExtractionContext,
    DocIndexingContext,
    Document,
    ListingPayload,
    SlimDocumentStub,
)
from onyx.file_store.file_store import FileStore, get_default_file_store
from onyx.utils.logger import setup_logger

logger = setup_logger()

_ItemT = TypeVar("_ItemT")

_BATCH_PATH_PREFIX = "iab"
# Backfill batches live apart, so a backfill never deletes or reissues the
# leftover batches a normal attempt resumes from, and vice versa.
_BACKFILL_BATCH_PATH_PREFIX = "iab_backfill"
# Stub batches wait for the conversion stage. Stub batch N becomes document
# batch N.
_STUB_BATCH_PATH_PREFIX = "isb"
_BACKFILL_STUB_BATCH_PATH_PREFIX = "isb_backfill"


def _has_legacy_tabular_section(doc_dict: dict) -> bool:
    """True if a section is a pre-`csv_file_id` tabular section (inline text only).
    Such a section was staged by an older docfetcher and the current file-backed-only
    `TabularSection` can't validate it; during rolling-deploy skew we skip the doc
    rather than fail the whole batch on `model_validate`."""
    sections = doc_dict.get("sections")
    if not isinstance(sections, list):
        return False
    return any(
        isinstance(s, dict) and s.get("type") == "tabular" and not s.get("csv_file_id")
        for s in sections
    )


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

    def __init__(
        self, cc_pair_id: int, index_attempt_id: int, is_backfill: bool = False
    ):
        self.cc_pair_id = cc_pair_id
        self.index_attempt_id = index_attempt_id
        self.is_backfill = is_backfill
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
    def update_old_batches_to_new_index_attempt(
        self, batch_names: list[str]
    ) -> list[str]:
        """Move the given batches to this index attempt, so docprocessing tasks
        of this attempt can re-issue them. Returns the new names of the batches
        it moved. A batch deleted before its move is left out."""

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
        documents: list[Document] = []
        for doc_dict in doc_dicts:
            if _has_legacy_tabular_section(doc_dict):
                logger.warning(
                    "Skipping doc %s with a legacy inline tabular section "
                    "(no csv_file_id); it re-indexes on the next attempt",
                    doc_dict.get("id", "unknown"),
                )
                continue
            documents.append(
                Document.model_validate(self._normalize_doc_dict(doc_dict))
            )
        return documents

    def _normalize_doc_dict(self, doc_dict: dict) -> dict:
        """Normalize document dict to handle legacy data with non-string metadata values.

        Before the _convert_to_metadata_value fix, Salesforce connector stored raw
        types (bool, float, None) in metadata. This converts them to strings for
        backward compatibility.
        """
        if "metadata" not in doc_dict:
            return doc_dict

        metadata = doc_dict["metadata"]
        if not isinstance(metadata, dict):
            return doc_dict

        normalized_metadata: dict[str, str | list[str]] = {}
        converted_keys: list[str] = []
        for key, value in metadata.items():
            if isinstance(value, list):
                normalized_metadata[key] = [str(item) for item in value]
            elif isinstance(value, str):
                normalized_metadata[key] = value
            else:
                # Convert bool, int, float, None to string
                converted_keys.append(f"{key}={type(value).__name__}")
                normalized_metadata[key] = str(value)

        if converted_keys:
            doc_id = doc_dict.get("id", "unknown")
            logger.warning(
                "Normalized legacy metadata for document %s: %s", doc_id, converted_keys
            )

        doc_dict["metadata"] = normalized_metadata
        return doc_dict

    def _path_prefix(self) -> str:
        return _BACKFILL_BATCH_PATH_PREFIX if self.is_backfill else _BATCH_PATH_PREFIX

    def _per_cc_pair_base_path(self) -> str:
        """Get the base path for the cc pair."""
        return f"{self._path_prefix()}/{self.cc_pair_id}"


class FileStoreDocumentBatchStorage(DocumentBatchStorage):
    """FileStore-based implementation of document batch storage."""

    def __init__(
        self,
        cc_pair_id: int,
        index_attempt_id: int,
        file_store: FileStore,
        is_backfill: bool = False,
    ):
        super().__init__(cc_pair_id, index_attempt_id, is_backfill)
        self.file_store = file_store

    def _get_batch_file_name(self, batch_num: int) -> str:
        """Generate file name for a document batch."""
        return f"{self.base_path}/{batch_num}.json"

    def store_batch(self, batch_num: int, documents: list[Document]) -> None:
        """Store a batch of documents using FileStore."""
        self._write_batch_file(
            batch_num,
            lambda: self._serialize_documents(documents),
            len(documents),
            f"Document Batch {batch_num}",
        )

    def _write_batch_file(
        self,
        batch_num: int,
        serialize: Callable[[], str],
        item_count: int,
        display_name: str,
    ) -> None:
        file_name = self._get_batch_file_name(batch_num)
        # An overwrite would repoint a re-issued batch's record at this batch
        # and lose its documents.
        if self.file_store.has_file(
            file_id=file_name,
            file_origin=FileOrigin.OTHER,
            file_type="application/json",
        ):
            raise RuntimeError(f"Batch {file_name} already exists")
        try:
            content = StringIO(serialize())

            self.file_store.save_file(
                file_id=file_name,
                content=content,
                display_name=display_name,
                file_origin=FileOrigin.OTHER,
                file_type="application/json",
                file_metadata={
                    "batch_num": batch_num,
                    "document_count": str(item_count),
                },
            )

            logger.debug(
                "Stored batch %s with %s items to FileStore as %s",
                batch_num,
                item_count,
                file_name,
            )
        except Exception as e:
            logger.error("Failed to store batch %s: %s", batch_num, e)
            raise

    def get_batch(self, batch_num: int) -> list[Document] | None:
        """Retrieve a batch of documents from FileStore."""
        return self._read_batch_file(batch_num, self._deserialize_documents)

    def _read_batch_file(
        self, batch_num: int, deserialize: Callable[[str], list[_ItemT]]
    ) -> list[_ItemT] | None:
        file_name = self._get_batch_file_name(batch_num)
        try:
            # Check if file exists
            if not self.file_store.has_file(
                file_id=file_name,
                file_origin=FileOrigin.OTHER,
                file_type="application/json",
            ):
                logger.warning(
                    "Batch %s not found in FileStore with name %s", batch_num, file_name
                )
                return None

            content_io = self.file_store.read_file(file_name)
            data = content_io.read().decode("utf-8")

            items = deserialize(data)
            logger.debug(
                "Retrieved batch %s with %s items from FileStore",
                batch_num,
                len(items),
            )
            return items
        except Exception as e:
            logger.error("Failed to retrieve batch %s: %s", batch_num, e)
            raise

    def delete_batch_by_name(self, batch_file_name: str) -> None:
        """Delete a specific batch from FileStore."""
        self.file_store.delete_file(batch_file_name, error_on_missing=False)
        logger.debug("Deleted batch %s from FileStore", batch_file_name)

    def delete_batch_by_num(self, batch_num: int) -> None:
        """Delete a specific batch from FileStore."""
        batch_file_name = self._get_batch_file_name(batch_num)
        self.delete_batch_by_name(batch_file_name)
        logger.debug(
            "Deleted batch num %s %s from FileStore", batch_num, batch_file_name
        )

    def cleanup_all_batches(self) -> None:
        """Delete all batches of the cc pair, and its stub batches too."""
        for batch_file_name in self.get_all_batches_for_cc_pair():
            self.delete_batch_by_name(batch_file_name)
        _StubBatchFiles(
            self.cc_pair_id, self.index_attempt_id, self.file_store, self.is_backfill
        ).cleanup_all_batches()

    def get_all_batches_for_cc_pair(self) -> list[str]:
        """Get all IDs of batches stored in the file store for the cc pair
        this batch store was initialized with.
        This includes any batches left over from a previous
        indexing attempt that need to be processed.
        """
        return [
            file.file_id
            for file in self.file_store.list_files_by_prefix(
                f"{self._per_cc_pair_base_path()}/"
            )
        ]

    def update_old_batches_to_new_index_attempt(
        self, batch_names: list[str]
    ) -> list[str]:
        moved_batch_names: list[str] = []
        for batch_file_name in batch_names:
            path_info = self.extract_path_info(batch_file_name)
            if path_info is None:
                logger.warning(
                    "Could not extract path info from batch file: %s", batch_file_name
                )
                continue
            if path_info.cc_pair_id != self.cc_pair_id:
                logger.warning(
                    "Skipping batch file %s owned by cc_pair %s",
                    batch_file_name,
                    path_info.cc_pair_id,
                )
                continue
            new_batch_file_name = self._get_batch_file_name(path_info.batch_num)
            # The old attempt's task deleted the batch after processing it.
            if not self.file_store.change_file_id(batch_file_name, new_batch_file_name):
                logger.info("Batch %s was deleted before its move", batch_file_name)
                continue
            moved_batch_names.append(new_batch_file_name)
        return moved_batch_names

    def extract_path_info(self, path: str) -> BatchStoragePathInfo | None:
        """Extract path info from a path."""
        path_spl = path.split("/")
        # TODO: remove this in a few months, just for backwards compatibility
        if len(path_spl) == 3:
            path_spl = [_BATCH_PATH_PREFIX] + path_spl
        try:
            _, cc_pair_id, index_attempt_id, batch_num = path_spl
            return BatchStoragePathInfo(
                cc_pair_id=int(cc_pair_id),
                index_attempt_id=int(index_attempt_id),
                batch_num=int(batch_num.split(".")[0]),  # remove .json
            )
        except Exception as e:
            logger.error("Failed to extract path info from %s: %s", path, e)
            return None


class _StubBatchFiles(FileStoreDocumentBatchStorage):
    """The file operations of the document batch store, under the stub
    batch prefix. Only `StubBatchStorage` uses it."""

    def _path_prefix(self) -> str:
        return (
            _BACKFILL_STUB_BATCH_PATH_PREFIX
            if self.is_backfill
            else _STUB_BATCH_PATH_PREFIX
        )

    def cleanup_all_batches(self) -> None:
        for batch_file_name in self.get_all_batches_for_cc_pair():
            self.delete_batch_by_name(batch_file_name)

    def renumber_old_batches(self, first_batch_num: int) -> int:
        """Moves every stub batch of the cc_pair to this attempt, with new
        numbers from `first_batch_num` up and no gap. Returns the count."""
        old_batches: list[tuple[int, int, str]] = []
        for batch_file_name in self.get_all_batches_for_cc_pair():
            path_info = self.extract_path_info(batch_file_name)
            if path_info is None or path_info.cc_pair_id != self.cc_pair_id:
                logger.warning("Skipping stub batch file %s", batch_file_name)
                continue
            old_batches.append(
                (path_info.index_attempt_id, path_info.batch_num, batch_file_name)
            )
        moved = 0
        for _, _, batch_file_name in sorted(old_batches):
            new_batch_file_name = self._get_batch_file_name(first_batch_num + moved)
            if batch_file_name == new_batch_file_name:
                moved += 1
                continue
            # The old attempt's task deleted the batch after it converted it.
            if not self.file_store.change_file_id(batch_file_name, new_batch_file_name):
                logger.info(
                    "Stub batch %s was deleted before its move", batch_file_name
                )
                continue
            moved += 1
        return moved


class StubBatchStorage:
    """Stores the stub batches of an index attempt: listed documents that
    the conversion stage has not fetched yet. Same file layout and API as
    the document batch store, under its own prefix."""

    def __init__(
        self,
        cc_pair_id: int,
        index_attempt_id: int,
        file_store: FileStore,
        is_backfill: bool = False,
    ):
        self._files = _StubBatchFiles(
            cc_pair_id, index_attempt_id, file_store, is_backfill
        )

    def store_batch(self, batch_num: int, stubs: list[SlimDocumentStub]) -> None:
        self._files._write_batch_file(
            batch_num,
            lambda: json.dumps([stub.model_dump(mode="json") for stub in stubs]),
            len(stubs),
            f"Stub Batch {batch_num}",
        )

    def get_batch(
        self,
        batch_num: int,
        payload_type: type[ListingPayload] | None = None,
    ) -> list[SlimDocumentStub] | None:
        """`payload_type` is the connector's `ListingPayload` subclass.
        Without it, the listing payload loads as the base model and loses
        its fields."""
        return self._files._read_batch_file(
            batch_num, lambda data: _deserialize_stubs(data, payload_type)
        )

    def delete_batch_by_num(self, batch_num: int) -> None:
        self._files.delete_batch_by_num(batch_num)

    def delete_batch_by_name(self, batch_file_name: str) -> None:
        self._files.delete_batch_by_name(batch_file_name)

    def cleanup_all_batches(self) -> None:
        self._files.cleanup_all_batches()

    def get_all_batches_for_cc_pair(self) -> list[str]:
        return self._files.get_all_batches_for_cc_pair()

    def update_old_batches_to_new_index_attempt(
        self, batch_names: list[str]
    ) -> list[str]:
        return self._files.update_old_batches_to_new_index_attempt(batch_names)

    def renumber_old_batches(self, first_batch_num: int) -> int:
        """Takes over the stub batches that earlier attempts of the cc_pair
        left. They get this attempt's numbers from `first_batch_num` up,
        with no gap, because a claim hands out a dense range. Returns the
        count."""
        return self._files.renumber_old_batches(first_batch_num)

    def stored_batch_nums(self) -> set[int]:
        """The numbers of this attempt's stub batches that are in the store."""
        batch_nums: set[int] = set()
        for batch_file_name in self.get_all_batches_for_cc_pair():
            path_info = self.extract_path_info(batch_file_name)
            if (
                path_info is not None
                and path_info.index_attempt_id == self._files.index_attempt_id
            ):
                batch_nums.add(path_info.batch_num)
        return batch_nums

    def extract_path_info(self, path: str) -> BatchStoragePathInfo | None:
        return self._files.extract_path_info(path)


def _deserialize_stubs(
    data: str, payload_type: type[ListingPayload] | None
) -> list[SlimDocumentStub]:
    stubs: list[SlimDocumentStub] = []
    for stub_dict in json.loads(data):
        raw_payload = stub_dict.pop("listing_payload", None)
        stub = SlimDocumentStub.model_validate(stub_dict)
        if raw_payload is not None:
            stub.listing_payload = (payload_type or ListingPayload).model_validate(
                raw_payload
            )
        stubs.append(stub)
    return stubs


def get_stub_batch_storage(
    cc_pair_id: int, index_attempt_id: int, *, is_backfill: bool
) -> StubBatchStorage:
    return StubBatchStorage(
        cc_pair_id, index_attempt_id, get_default_file_store(), is_backfill
    )


def get_document_batch_storage(
    cc_pair_id: int, index_attempt_id: int, *, is_backfill: bool
) -> DocumentBatchStorage:
    """Factory function to get the configured document batch storage implementation."""
    # The get_default_file_store will now correctly use S3BackedFileStore
    # or other configured stores based on environment variables
    file_store = get_default_file_store()
    return FileStoreDocumentBatchStorage(
        cc_pair_id, index_attempt_id, file_store, is_backfill
    )
