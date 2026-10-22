import time
from datetime import datetime, timedelta
from io import BytesIO

from ee.onyx.external_permissions.perm_sync_types import (
    DocSyncCheckpointer,
    DocSyncResume,
)
from onyx.background.indexing.checkpointing_utils import check_checkpoint_size
from onyx.configs.constants import NUM_DAYS_TO_KEEP_CHECKPOINTS, FileOrigin
from onyx.connectors.models import ConnectorCheckpoint
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.permission_sync_attempt import (
    get_resumable_doc_permission_sync_checkpoint,
    set_doc_permission_sync_attempt_checkpoint,
)
from onyx.file_store.file_store import get_default_file_store
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Bounds file store and DB writes; a stopped attempt loses at most this much crawl.
CHECKPOINT_SAVE_INTERVAL_SECONDS = 5 * 60


def _checkpoint_pointer(attempt_id: int) -> str:
    return f"perm_sync_checkpoint_{attempt_id}.json"


def _delete_checkpoint(attempt_id: int, checkpoint_pointer: str) -> None:
    get_default_file_store().delete_file(checkpoint_pointer)
    with get_session_with_current_tenant() as db_session:
        set_doc_permission_sync_attempt_checkpoint(db_session, attempt_id, None)


class FileStoreDocSyncCheckpointer(DocSyncCheckpointer):
    """Saves each attempt's checkpoint under its own pointer. The attempt it
    resumed keeps its checkpoint until this one saves, so a crash before the
    first save still leaves something to resume."""

    def __init__(
        self, cc_pair_id: int, attempt_id: int, connector_config_hash: str | None
    ) -> None:
        self.attempt_id = attempt_id
        self._connector_config_hash = connector_config_hash
        self._resume: DocSyncResume | None = None
        self._resumed_attempt_id: int | None = None
        self._resumed_pointer: str | None = None
        self._saved_pointer: str | None = None
        self._frozen = False
        self._last_save_monotonic = time.monotonic()

        with get_session_with_current_tenant() as db_session:
            ref = get_resumable_doc_permission_sync_checkpoint(
                db_session,
                cc_pair_id=cc_pair_id,
                current_attempt_id=attempt_id,
                max_age=timedelta(days=NUM_DAYS_TO_KEEP_CHECKPOINTS),
                connector_config_hash=connector_config_hash,
            )
        if ref is None:
            return

        try:
            checkpoint_io = get_default_file_store().read_file(
                ref.checkpoint_pointer, mode="rb"
            )
            checkpoint_json = checkpoint_io.read().decode("utf-8")
        except Exception:
            logger.exception(
                "Could not load the permission sync checkpoint of attempt %s; starting fresh",
                ref.attempt_id,
            )
            return

        logger.info(
            "Resuming permission sync of cc_pair=%s from attempt %s",
            cc_pair_id,
            ref.attempt_id,
        )
        self._resume = DocSyncResume(
            checkpoint_json=checkpoint_json,
            poll_range_start=ref.poll_range_start,
            poll_range_end=ref.poll_range_end,
        )
        self._resumed_attempt_id = ref.attempt_id
        self._resumed_pointer = ref.checkpoint_pointer

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

        check_checkpoint_size(checkpoint)
        pointer = _checkpoint_pointer(self.attempt_id)
        get_default_file_store().save_file(
            content=BytesIO(checkpoint.model_dump_json().encode()),
            display_name=pointer,
            file_origin=FileOrigin.PERM_SYNC_CHECKPOINT,
            file_type="application/json",
            file_id=pointer,
        )
        with get_session_with_current_tenant() as db_session:
            set_doc_permission_sync_attempt_checkpoint(
                db_session,
                self.attempt_id,
                pointer,
                poll_range_start=poll_range_start,
                poll_range_end=poll_range_end,
                connector_config_hash=self._connector_config_hash,
            )
        self._saved_pointer = pointer

        if self._resumed_attempt_id is not None and self._resumed_pointer is not None:
            _delete_checkpoint(self._resumed_attempt_id, self._resumed_pointer)
            self._resumed_attempt_id = None
            self._resumed_pointer = None

    def freeze(self) -> None:
        """Stop saving after a failed element write, so a resume starts before
        that element and retries it."""
        self._frozen = True

    def discard(self) -> None:
        """Drop every checkpoint this chain holds, once the crawl has finished.
        Never raises: the attempt already succeeded, and a later success keeps a
        leftover checkpoint from being resumed."""
        holders = [
            (self.attempt_id, self._saved_pointer),
            (self._resumed_attempt_id, self._resumed_pointer),
        ]
        for attempt_id, pointer in holders:
            if attempt_id is None or pointer is None:
                continue
            try:
                _delete_checkpoint(attempt_id, pointer)
            except Exception:
                logger.exception(
                    "Could not delete the permission sync checkpoint of attempt %s",
                    attempt_id,
                )
        self._saved_pointer = None
        self._resumed_attempt_id = None
        self._resumed_pointer = None
