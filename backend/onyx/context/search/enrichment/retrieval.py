"""The lane that retrieves a withheld source and clears it with its provider.

Split in two on purpose. Resolving which sources are live, and with whose
credentials, needs a database session; running the search does not. The
chat path resolves ahead of time and hands the result down, as it already
does for federated search.
"""

import threading
from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict, PrivateAttr
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.event_inbox.credentials import pair_secrets
from onyx.connectors.event_inbox.sources import load_event_sources
from onyx.context.search.enrichment.registry import (
    ChunkPermissionFilter,
    enrichment_source_types,
    get_enrichment_filter,
)
from onyx.context.search.models import InferenceChunk
from onyx.db.connector_credential_pair import get_active_cc_pairs_for_source
from onyx.db.models import User
from onyx.utils.logger import setup_logger

logger = setup_logger()


class EnrichmentContext(BaseModel):
    """One live withheld source, ready to be searched for one user.

    One of these is built per search and shared by every lane of it, so it
    is also where the search remembers what the provider already said.
    The lanes run in parallel threads, hence the lock.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    source: DocumentSource
    permission_filter: ChunkPermissionFilter
    user_email: str
    secrets: Mapping[str, str]

    # document id -> may this user read it. One search expands into several
    # queries, and they retrieve overlapping documents.
    _decisions: dict[str, bool] = PrivateAttr(default_factory=dict)
    # Set once the provider has failed in this search. Asking again would
    # answer no faster and spend the rate limit that caused it.
    _unreachable: bool = PrivateAttr(default=False)
    _lock: threading.Lock = PrivateAttr(default_factory=threading.Lock)

    def allowed(self, chunks: Sequence[InferenceChunk]) -> list[InferenceChunk]:
        """The chunks the provider says this user may read.

        A filter that raises drops the whole lane rather than the chunk it
        failed on: the alternative is returning content nobody cleared.
        """
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
        """The provider's verdict per document, or None if it could not
        answer. A document it did not clear is refused, whether it said no
        or the filter could not identify the chunk."""
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


def get_enrichment_contexts(
    db_session: Session,
    user: User | None,
    source_types: Sequence[DocumentSource] | None,
) -> list[EnrichmentContext]:
    """The withheld sources this user can be served right now.

    Anonymous users get none: the provider answers about a named user, and
    there is nobody to name.
    """
    if user is None or not user.email:
        return []

    load_event_sources()

    contexts: list[EnrichmentContext] = []
    for source in enrichment_source_types():
        # An explicit source selection scopes this lane as it scopes the
        # default one.
        if source_types is not None and source not in source_types:
            continue
        permission_filter = get_enrichment_filter(source)
        if permission_filter is None:
            continue
        pairs = get_active_cc_pairs_for_source(db_session, source)
        if not pairs:
            continue
        # One pair per source, as the event inbox resolves it: a second
        # account needs a routing key neither side declares yet.
        contexts.append(
            EnrichmentContext(
                source=source,
                permission_filter=permission_filter,
                user_email=user.email,
                secrets=pair_secrets(pairs[0]),
            )
        )
    return contexts
