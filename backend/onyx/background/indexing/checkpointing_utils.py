from datetime import datetime
from datetime import timedelta
from io import BytesIO

from sqlalchemy import and_
from sqlalchemy.orm import Session

from onyx.configs.constants import FileOrigin
from onyx.configs.constants import NUM_DAYS_TO_KEEP_CHECKPOINTS
from onyx.connectors.interfaces import BaseConnector
from onyx.connectors.interfaces import CheckpointedConnector
from onyx.connectors.models import ConnectorCheckpoint
from onyx.db.engine.time_utils import get_db_current_time
from onyx.db.index_attempt import get_index_attempt
from onyx.db.index_attempt import get_recent_completed_attempts_for_cc_pair
from onyx.db.models import IndexAttempt
from onyx.db.models import IndexingStatus
from onyx.file_store.file_store import get_default_file_store
from onyx.utils.logger import setup_logger
from onyx.utils.object_size_check import deep_getsizeof

logger = setup_logger()

_NUM_RECENT_ATTEMPTS_TO_CONSIDER = 50


def _build_checkpoint_pointer(index_attempt_id: int) -> str:
    return f"checkpoint_{index_attempt_id}.json"


def save_checkpoint(
    db_session: Session, index_attempt_id: int, checkpoint: ConnectorCheckpoint
) -> str:
    """Save a checkpoint for a given index attempt to the file store"""
    checkpoint_pointer = _build_checkpoint_pointer(index_attempt_id)

    file_store = get_default_file_store()
    file_store.save_file(
        content=BytesIO(checkpoint.model_dump_json().encode()),
        display_name=checkpoint_pointer,
        file_origin=FileOrigin.INDEXING_CHECKPOINT,
        file_type="application/json",
        file_id=checkpoint_pointer,
    )

    index_attempt = get_index_attempt(db_session, index_attempt_id)
    if not index_attempt:
        raise RuntimeError(f"Index attempt {index_attempt_id} not found in DB.")
    index_attempt.checkpoint_pointer = checkpoint_pointer
    db_session.add(index_attempt)
    db_session.commit()
    return checkpoint_pointer


def load_checkpoint(
    index_attempt_id: int, connector: BaseConnector
) -> ConnectorCheckpoint:
    """Load a checkpoint for a given index attempt from the file store"""
    checkpoint_pointer = _build_checkpoint_pointer(index_attempt_id)
    file_store = get_default_file_store()
    checkpoint_io = file_store.read_file(checkpoint_pointer, mode="rb")
    checkpoint_data = checkpoint_io.read().decode("utf-8")
    if isinstance(connector, CheckpointedConnector):
        return connector.validate_checkpoint_json(checkpoint_data)
    return ConnectorCheckpoint.model_validate_json(checkpoint_data)


def get_latest_valid_checkpoint(
    db_session: Session,
    cc_pair_id: int,
    search_settings_id: int,
    window_start: datetime,
    window_end: datetime,
    connector: BaseConnector,
) -> tuple[ConnectorCheckpoint, bool]:
    """Get the latest valid checkpoint for a given connector credential pair"""
    checkpoint_candidates = get_recent_completed_attempts_for_cc_pair(
        cc_pair_id=cc_pair_id,
        search_settings_id=search_settings_id,
        db_session=db_session,
        limit=_NUM_RECENT_ATTEMPTS_TO_CONSIDER,
    )

    # don't keep using checkpoints if we've had a bunch of failed attempts in a row
    # where we make no progress. Only do this if we have had at least
    # _NUM_RECENT_ATTEMPTS_TO_CONSIDER completed attempts.
    if len(checkpoint_candidates) >= _NUM_RECENT_ATTEMPTS_TO_CONSIDER:
        had_any_progress = False
        for candidate in checkpoint_candidates:
            if (
                candidate.total_docs_indexed is not None
                and candidate.total_docs_indexed > 0
            ) or candidate.status.is_successful():
                had_any_progress = True
                break

        if not had_any_progress:
            logger.warning(
                f"{_NUM_RECENT_ATTEMPTS_TO_CONSIDER} consecutive failed attempts without progress "
                f"found for cc_pair={cc_pair_id}. Ignoring checkpoint to let the run start "
                "from scratch."
            )
            return connector.build_dummy_checkpoint(), False

    # filter out any candidates that don't meet the criteria
    checkpoint_candidates = [
        candidate
        for candidate in checkpoint_candidates
        if (
            candidate.poll_range_start == window_start
            and candidate.poll_range_end == window_end
            and (
                candidate.status == IndexingStatus.FAILED
                # if the background job was killed (and thus the attempt was canceled)
                # we still want to use the checkpoint so that we can pick up where we left off
                or candidate.status == IndexingStatus.CANCELED
            )
            and candidate.checkpoint_pointer is not None
            # NOTE: There are a couple connectors that may make progress but not have
            # any "total_docs_indexed". E.g. they are going through
            # Slack channels, and tons of them don't have any updates.
            # Leaving the below in as historical context / in-case we want to use it again.
            # we want to make sure that the checkpoint is actually useful
            # if it's only gone through a few docs, it's probably not worth
            # using. This also avoids weird cases where a connector is basically
            # non-functional but still "makes progress" by slowly moving the
            # checkpoint forward run after run
            # and candidate.total_docs_indexed
            # and candidate.total_docs_indexed > 100
        )
    ]

    # assumes latest checkpoint is the furthest along. This only isn't true
    # if something else has gone wrong.
    latest_valid_checkpoint_candidate = (
        checkpoint_candidates[0] if checkpoint_candidates else None
    )

    checkpoint = connector.build_dummy_checkpoint()
    if latest_valid_checkpoint_candidate is None:
        logger.info(
            f"No valid checkpoint found for cc_pair={cc_pair_id}. Starting from scratch."
        )
        return checkpoint, False

    try:
        previous_checkpoint = load_checkpoint(
            index_attempt_id=latest_valid_checkpoint_candidate.id,
            connector=connector,
        )
    except Exception:
        logger.exception(
            f"Failed to load checkpoint from previous failed attempt with ID "
            f"{latest_valid_checkpoint_candidate.id}. Falling back to default checkpoint."
        )
        return checkpoint, False

    logger.info(
        f"Using checkpoint from previous failed attempt with ID "
        f"{latest_valid_checkpoint_candidate.id}. Previous checkpoint: "
        f"{previous_checkpoint}"
    )
    return previous_checkpoint, True


def get_index_attempts_with_old_checkpoints(
    db_session: Session, days_to_keep: int = NUM_DAYS_TO_KEEP_CHECKPOINTS
) -> list[IndexAttempt]:
    """Get all index attempts with checkpoints older than the specified number of days.

    Args:
        db_session: The database session
        days_to_keep: Number of days to keep checkpoints for (default: NUM_DAYS_TO_KEEP_CHECKPOINTS)

    Returns:
        List of IndexAttempt objects with old checkpoints
    """
    cutoff_date = get_db_current_time(db_session) - timedelta(days=days_to_keep)

    # Find all index attempts with checkpoints older than cutoff_date
    old_attempts = (
        db_session.query(IndexAttempt)
        .filter(
            and_(
                IndexAttempt.checkpoint_pointer.isnot(None),
                IndexAttempt.time_created < cutoff_date,
            )
        )
        .all()
    )

    return old_attempts


def cleanup_checkpoint(db_session: Session, index_attempt_id: int) -> None:
    """Clean up a checkpoint for a given index attempt"""
    index_attempt = get_index_attempt(db_session, index_attempt_id)
    if not index_attempt:
        raise RuntimeError(f"Index attempt {index_attempt_id} not found in DB.")

    if not index_attempt.checkpoint_pointer:
        return None

    file_store = get_default_file_store()
    file_store.delete_file(index_attempt.checkpoint_pointer)

    index_attempt.checkpoint_pointer = None
    db_session.add(index_attempt)
    db_session.commit()

    return None


def check_checkpoint_size(checkpoint: ConnectorCheckpoint) -> None:
    """Check if the checkpoint content size exceeds the limit (200MB)"""
    content_size = deep_getsizeof(checkpoint.model_dump())
    if content_size > 200_000_000:  # 200MB in bytes
        raise ValueError(
            f"Checkpoint content size ({content_size} bytes) exceeds 200MB limit"
        )
