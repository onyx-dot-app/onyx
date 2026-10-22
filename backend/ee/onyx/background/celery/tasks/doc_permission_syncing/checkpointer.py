import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from io import BytesIO

from pydantic import BaseModel

from ee.onyx.external_permissions.perm_sync_types import (
    DocSyncCheckpointer,
    DocSyncResume,
)
from onyx.background.indexing.checkpointing_utils import check_checkpoint_size
from onyx.configs.constants import NUM_DAYS_TO_KEEP_CHECKPOINTS, FileOrigin
from onyx.connectors.models import ConnectorCheckpoint
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.permission_sync_attempt import is_doc_permission_sync_attempt_resumable
from onyx.file_store.file_store import get_default_file_store
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Bounds file store writes. A stopped attempt loses at most this much crawl.
CHECKPOINT_SAVE_INTERVAL_SECONDS = 5 * 60
_CHECKPOINT_FILE_TYPE = "application/json"


class _SavedDocSyncCheckpoint(BaseModel):
    """The checkpoint file: the crawl state plus what decides whether a later
    attempt may continue it."""

    attempt_id: int
    saved_at: datetime
    connector_config_hash: str | None
    poll_range_start: datetime | None
    poll_range_end: datetime
    checkpoint_json: str


def _checkpoint_pointer(cc_pair_id: int) -> str:
    return f"perm_sync_checkpoint_cc_pair_{cc_pair_id}.json"


def _delete_checkpoint_file(pointer: str) -> None:
    """Never raises: callers have already committed the state that made the
    checkpoint stale, and the resume check refuses a leftover one anyway."""
    try:
        get_default_file_store().delete_file(pointer, error_on_missing=False)
    except Exception:
        logger.exception("Could not delete the permission sync checkpoint %s", pointer)


def delete_doc_sync_checkpoint(cc_pair_id: int) -> None:
    _delete_checkpoint_file(_checkpoint_pointer(cc_pair_id))


def _load_saved_checkpoint(pointer: str) -> _SavedDocSyncCheckpoint | None:
    file_store = get_default_file_store()
    if not file_store.has_file(
        pointer, FileOrigin.PERM_SYNC_CHECKPOINT, _CHECKPOINT_FILE_TYPE
    ):
        return None
    try:
        return _SavedDocSyncCheckpoint.model_validate_json(
            file_store.read_file(pointer, mode="rb").read()
        )
    except Exception:
        logger.exception("Could not load the permission sync checkpoint %s", pointer)
        return None


class FileStoreDocSyncCheckpointer(DocSyncCheckpointer):
    """One checkpoint file per cc_pair, overwritten on every save and deleted
    when a crawl finishes. A failed attempt leaves its last save for the next
    attempt, which is why only a failed attempt's save may be resumed."""

    def __init__(
        self,
        cc_pair_id: int,
        attempt_id: int,
        connector_config_hash: str | None,
        flush_pending_writes: Callable[[], None],
    ) -> None:
        """``flush_pending_writes`` runs before every save: the task writes
        elements in batches, and a checkpoint may only cover written ones."""
        self._pointer = _checkpoint_pointer(cc_pair_id)
        self._attempt_id = attempt_id
        self._connector_config_hash = connector_config_hash
        self._flush_pending_writes = flush_pending_writes
        self._frozen = False
        self._last_save_monotonic = time.monotonic()
        self._resume = self._find_resume(cc_pair_id)

    def _find_resume(self, cc_pair_id: int) -> DocSyncResume | None:
        saved = _load_saved_checkpoint(self._pointer)
        if saved is None:
            return None
        if saved.connector_config_hash != self._connector_config_hash:
            return None
        if saved.saved_at < datetime.now(timezone.utc) - timedelta(
            days=NUM_DAYS_TO_KEEP_CHECKPOINTS
        ):
            return None
        with get_session_with_current_tenant() as db_session:
            resumable = is_doc_permission_sync_attempt_resumable(
                db_session,
                cc_pair_id=cc_pair_id,
                attempt_id=saved.attempt_id,
                current_attempt_id=self._attempt_id,
            )
        if not resumable:
            return None

        logger.info(
            "Resuming permission sync of cc_pair=%s from attempt %s",
            cc_pair_id,
            saved.attempt_id,
        )
        return DocSyncResume(
            checkpoint_json=saved.checkpoint_json,
            poll_range_start=saved.poll_range_start,
            poll_range_end=saved.poll_range_end,
        )

    @property
    def resume(self) -> DocSyncResume | None:
        return self._resume

    def save(
        self,
        checkpoint: ConnectorCheckpoint,
        poll_range_start: datetime | None,
        poll_range_end: datetime,
    ) -> None:
        if self._frozen:
            return
        now = time.monotonic()
        if now - self._last_save_monotonic < CHECKPOINT_SAVE_INTERVAL_SECONDS:
            return
        self._last_save_monotonic = now

        # A failed write in the flush freezes this checkpointer
        self._flush_pending_writes()
        if self._frozen:
            return

        check_checkpoint_size(checkpoint)
        saved = _SavedDocSyncCheckpoint(
            attempt_id=self._attempt_id,
            saved_at=datetime.now(timezone.utc),
            connector_config_hash=self._connector_config_hash,
            poll_range_start=poll_range_start,
            poll_range_end=poll_range_end,
            checkpoint_json=checkpoint.model_dump_json(),
        )
        get_default_file_store().save_file(
            content=BytesIO(saved.model_dump_json().encode()),
            display_name=self._pointer,
            file_origin=FileOrigin.PERM_SYNC_CHECKPOINT,
            file_type=_CHECKPOINT_FILE_TYPE,
            file_id=self._pointer,
        )

    def freeze(self) -> None:
        """Stop saving after a failed element write, so a resume starts before
        that element and retries it."""
        self._frozen = True

    def discard(self) -> None:
        """Drop the pair's checkpoint once the crawl has finished."""
        _delete_checkpoint_file(self._pointer)
