"""What one live withheld source looks like to the search path."""

import threading
from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict, PrivateAttr

from onyx.configs.constants import DocumentSource
from onyx.context.search.enrichment.registry import ChunkPermissionFilter
from onyx.context.search.models import InferenceChunk
from onyx.utils.logger import setup_logger

logger = setup_logger()


class EnrichmentContext(BaseModel):
    """One live withheld source, searchable for one user.

    Built once per search and shared by every lane of it, so it is also
    where the search remembers what the provider already said. The lanes run
    in parallel threads, hence the lock.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    source: DocumentSource
    permission_filter: ChunkPermissionFilter
    user_email: str
    secrets: Mapping[str, str]

    # A search expands into several queries over overlapping documents.
    _decisions: dict[str, bool] = PrivateAttr(default_factory=dict)
    # Asking a failed provider again spends the rate limit that caused it.
    _unreachable: bool = PrivateAttr(default=False)
    _lock: threading.Lock = PrivateAttr(default_factory=threading.Lock)

    def allowed(self, chunks: Sequence[InferenceChunk]) -> list[InferenceChunk]:
        """The chunks the provider says this user may read. A filter that
        raises drops the lane, not just the chunk it failed on."""
        if not chunks:
            return []

        with self._lock:
            if self._unreachable:
                return []
            decided = dict(self._decisions)

        undecided = [chunk for chunk in chunks if chunk.document_id not in decided]
        if undecided:
            answered = self._ask(undecided)
            if answered is None:
                return []
            decided.update(answered)

        return [chunk for chunk in chunks if decided.get(chunk.document_id, False)]

    def _ask(self, chunks: list[InferenceChunk]) -> dict[str, bool] | None:
        """The verdict per document, or None if the provider could not
        answer. Anything it did not clear is refused."""
        try:
            cleared = self.permission_filter(
                user_email=self.user_email, chunks=chunks, secrets=self.secrets
            )
        except Exception:
            logger.exception(
                "The %s permission filter failed; returning none of its results",
                self.source.value,
            )
            with self._lock:
                self._unreachable = True
            return None

        allowed_ids = {chunk.document_id for chunk in cleared}
        answered = {
            chunk.document_id: chunk.document_id in allowed_ids for chunk in chunks
        }
        with self._lock:
            self._decisions.update(answered)
        return answered
