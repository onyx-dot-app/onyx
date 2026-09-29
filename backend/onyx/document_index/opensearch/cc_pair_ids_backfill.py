"""Progress of the backfill that sets cc_pair_ids on existing OpenSearch chunks.

Progress is kept per tenant in the KV store and is tied to one index name, so a
swap to a new primary index restarts the backfill on that index.
"""

from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.configs.constants import KV_CC_PAIR_IDS_BACKFILL_PROGRESS_KEY
from onyx.db.search_settings import get_current_search_settings
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError


class CCPairIdsBackfillProgress(BaseModel):
    index_name: str
    # cc-pairs that existed when the backfill started and are not done yet.
    # None until the first run takes the snapshot. cc-pairs created later get
    # cc_pair_ids at index time, so they are never added.
    pending_cc_pair_ids: list[int] | None = None
    # Cursor in the first pending cc-pair: every document with an ID <= this
    # one is done.
    last_document_id: str | None = None

    @property
    def completed(self) -> bool:
        return self.pending_cc_pair_ids == []


def load_cc_pair_ids_backfill_progress(index_name: str) -> CCPairIdsBackfillProgress:
    """Returns the stored progress for this index, or fresh progress if none is
    stored or the stored progress is for another index."""
    try:
        stored = get_kv_store().load(KV_CC_PAIR_IDS_BACKFILL_PROGRESS_KEY)
    except KvKeyNotFoundError:
        return CCPairIdsBackfillProgress(index_name=index_name)
    progress = CCPairIdsBackfillProgress.model_validate(stored)
    if progress.index_name != index_name:
        return CCPairIdsBackfillProgress(index_name=index_name)
    return progress


def store_cc_pair_ids_backfill_progress(progress: CCPairIdsBackfillProgress) -> None:
    get_kv_store().store(KV_CC_PAIR_IDS_BACKFILL_PROGRESS_KEY, progress.model_dump())


def is_cc_pair_ids_backfill_complete(db_session: Session) -> bool:
    """True once every cc-pair in the snapshot is done or deleted. Chunks indexed
    later get cc_pair_ids at index time, and metadata sync keeps the field
    current. After a swap to a new primary index, this is False until the
    backfill finishes on that index."""
    index_name = get_current_search_settings(db_session).index_name
    return load_cc_pair_ids_backfill_progress(index_name).completed
