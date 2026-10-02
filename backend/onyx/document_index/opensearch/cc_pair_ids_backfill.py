"""Progress of the backfill that sets cc_pair_ids on existing OpenSearch chunks.

Progress is kept per tenant in the KV store and is tied to one search settings
generation, so a swap to a new primary index restarts the backfill on that
index. A new generation can reuse an old index name, so the name is not the key.
"""

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from onyx.configs.constants import KV_CC_PAIR_IDS_BACKFILL_PROGRESS_KEY
from onyx.db.models import SearchSettings
from onyx.db.search_settings import get_current_search_settings
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.utils.logger import setup_logger

logger = setup_logger()


class CCPairIdsBackfillProgress(BaseModel):
    search_settings_id: int
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


def load_cc_pair_ids_backfill_progress(
    search_settings: SearchSettings,
) -> CCPairIdsBackfillProgress:
    """Returns the stored progress for this search settings generation, or fresh
    progress if none is stored or the stored progress is for another one."""
    fresh = CCPairIdsBackfillProgress(
        search_settings_id=search_settings.id,
        index_name=search_settings.index_name,
    )
    try:
        stored = get_kv_store().load(KV_CC_PAIR_IDS_BACKFILL_PROGRESS_KEY)
    except KvKeyNotFoundError:
        return fresh
    try:
        progress = CCPairIdsBackfillProgress.model_validate(stored)
    except ValidationError as e:
        # Progress stored before a field was added does not validate. The
        # backfill restarts, which only repeats idempotent writes.
        logger.warning(
            "cc_pair_ids backfill: stored progress does not validate, restarting: %s",
            e,
        )
        return fresh
    if (
        progress.search_settings_id != search_settings.id
        or progress.index_name != search_settings.index_name
    ):
        return fresh
    return progress


def store_cc_pair_ids_backfill_progress(progress: CCPairIdsBackfillProgress) -> None:
    get_kv_store().store(KV_CC_PAIR_IDS_BACKFILL_PROGRESS_KEY, progress.model_dump())


def is_cc_pair_ids_backfill_complete(db_session: Session) -> bool:
    """True once every cc-pair in the snapshot is done or deleted. Chunks indexed
    later get cc_pair_ids at index time, and metadata sync keeps the field
    current. After a swap to a new primary index, this is False until the
    backfill finishes on that index."""
    return load_cc_pair_ids_backfill_progress(
        get_current_search_settings(db_session)
    ).completed
