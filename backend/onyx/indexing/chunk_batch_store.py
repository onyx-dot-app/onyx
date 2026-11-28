import pickle
import shutil
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, BinaryIO

from onyx.connectors.models import Document
from onyx.indexing.models import IndexChunk


def _document_ref(index: int) -> Document:
    """Stands in a batch file for the source document at `index`. Only the
    store that wrote the file can resolve it."""
    raise RuntimeError(
        f"Bug: document reference {index} was loaded outside its ChunkBatchStore."
    )


class _ChunkUnpickler(pickle.Unpickler):
    def __init__(self, file: BinaryIO, documents: list[Document]) -> None:
        super().__init__(file)
        self._documents = documents

    def find_class(self, module: str, name: str) -> Any:
        if module == _document_ref.__module__ and name == _document_ref.__name__:
            return self._documents.__getitem__
        return super().find_class(module, name)


class ChunkBatchStore:
    """Manages serialization of embedded chunks to a temporary directory.

    Owns the temp directory lifetime and provides save/load/stream/scrub
    operations.

    A batch file holds a reference in place of each chunk's source document,
    and the store keeps the document in memory. A file that held the document
    would repeat a large document in each batch that holds one of its chunks.

    Use as a context manager to ensure cleanup::

        with ChunkBatchStore() as store:
            store.save(chunks, batch_idx=0)
            for chunk in store.stream():
                ...
    """

    _EXT = ".pkl"

    def __init__(self) -> None:
        self._tmpdir: Path | None = None
        # The list keeps each document alive, so its id() stays unique.
        self._documents: list[Document] = []
        self._document_index: dict[int, int] = {}

    # -- context manager -----------------------------------------------------

    def __enter__(self) -> "ChunkBatchStore":
        self._tmpdir = Path(tempfile.mkdtemp(prefix="onyx_embeddings_"))
        return self

    def __exit__(self, *_exc: object) -> None:
        if self._tmpdir is not None:
            shutil.rmtree(self._tmpdir, ignore_errors=True)
            self._tmpdir = None
        self._documents = []
        self._document_index = {}

    @property
    def _dir(self) -> Path:
        if self._tmpdir is None:
            raise RuntimeError("ChunkBatchStore used outside context manager")
        return self._tmpdir

    # -- storage primitives --------------------------------------------------

    def _reduce_document(
        self, document: Document
    ) -> tuple[Callable[..., Any], tuple[int]]:
        index = self._document_index.get(id(document))
        if index is None:
            index = len(self._documents)
            self._documents.append(document)
            self._document_index[id(document)] = index
        return _document_ref, (index,)

    def _dump(self, chunks: list[IndexChunk], batch_file: Path) -> None:
        with open(batch_file, "wb") as f:
            pickler = pickle.Pickler(f)
            # The table matches exact classes, so list each class in use.
            pickler.dispatch_table = dict.fromkeys(
                {type(chunk.source_document) for chunk in chunks},
                self._reduce_document,
            )
            pickler.dump(chunks)

    def save(self, chunks: list[IndexChunk], batch_idx: int) -> None:
        """Serialize a batch of embedded chunks to disk."""
        self._dump(chunks, self._dir / f"batch_{batch_idx}{self._EXT}")

    def _load(self, batch_file: Path) -> list[IndexChunk]:
        """Deserialize a batch of embedded chunks from a file."""
        with open(batch_file, "rb") as f:
            # Reads back files this process itself wrote in save().
            return _ChunkUnpickler(f, self._documents).load()

    def _batch_files(self) -> list[Path]:
        """Return batch files sorted by numeric index."""
        return sorted(
            self._dir.glob(f"batch_*{self._EXT}"),
            key=lambda p: int(p.stem.removeprefix("batch_")),
        )

    # -- higher-level operations ---------------------------------------------

    def stream(self) -> Iterator[IndexChunk]:
        """Yield all chunks across all batch files.

        Each call returns a fresh generator, so the data can be iterated
        multiple times (e.g. once per document index).
        """
        for batch_file in self._batch_files():
            yield from self._load(batch_file)

    def scrub_failed_docs(self, failed_doc_ids: set[str]) -> None:
        """Remove chunks belonging to *failed_doc_ids* from all batch files.

        When a document fails embedding in batch N, earlier batches may
        already contain successfully embedded chunks for that document.
        This ensures the output is all-or-nothing per document.
        """
        for batch_file in self._batch_files():
            batch_chunks = self._load(batch_file)
            cleaned = [
                c for c in batch_chunks if c.source_document.id not in failed_doc_ids
            ]
            if len(cleaned) != len(batch_chunks):
                self._dump(cleaned, batch_file)
