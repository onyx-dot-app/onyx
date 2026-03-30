import pickle
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

from onyx.indexing.models import IndexChunk


class ChunkBatchStore:
    """Manages serialization of embedded chunks to a temporary directory.

    Owns the temp directory lifetime and provides save/load/stream/scrub
    operations.

    Use as a context manager to ensure cleanup::

        with ChunkBatchStore() as store:
            store.save(chunks, batch_idx=0)
            for chunk in store.stream():
                ...
    """

    _EXT = ".pkl"

    def __init__(self) -> None:
        self._tmpdir: Path | None = None

    # -- context manager -----------------------------------------------------

    def __enter__(self) -> "ChunkBatchStore":
        self._tmpdir = Path(tempfile.mkdtemp(prefix="onyx_embeddings_"))
        return self

    def __exit__(self, *_exc: object) -> None:
        if self._tmpdir is not None:
            shutil.rmtree(self._tmpdir, ignore_errors=True)
            self._tmpdir = None

    @property
    def _dir(self) -> Path:
        assert self._tmpdir is not None, "ChunkBatchStore used outside context manager"
        return self._tmpdir

    # -- storage primitives --------------------------------------------------

    def save(self, chunks: list[IndexChunk], batch_idx: int) -> None:
        """Serialize a batch of embedded chunks to disk."""
        with open(self._dir / f"batch_{batch_idx}{self._EXT}", "wb") as f:
            pickle.dump(chunks, f)

    def _load(self, batch_file: Path) -> list[IndexChunk]:
        """Deserialize a batch of embedded chunks from a file."""
        with open(batch_file, "rb") as f:
            return pickle.load(f)

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
                with open(batch_file, "wb") as f:
                    pickle.dump(cleaned, f)
