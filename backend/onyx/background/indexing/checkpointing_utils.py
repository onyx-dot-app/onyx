from datetime import datetime
from datetime import timedelta
from io import BytesIO

from sqlalchemy import and_
from sqlalchemy.orm import Session

from onyx.configs.constants import FileOrigin
from onyx.connectors.models import ConnectorCheckpoint
from onyx.db.engine import get_db_current_time
from onyx.db.index_attempt import get_index_attempt
from onyx.db.index_attempt import get_recent_completed_attempts_for_cc_pair
from onyx.db.models import IndexAttempt
from onyx.db.models import IndexingStatus
from onyx.file_store.file_store import get_default_file_store
from onyx.utils.logger import setup_logger
from onyx.utils.object_size_check import deep_getsizeof


logger = setup_logger()

_NUM_RECENT_ATTEMPTS_TO_CONSIDER = 20
_NUM_DOCS_INDEXED_TO_BE_VALID_CHECKPOINT = 100


def _build_checkpoint_pointer(index_attempt_id: int) -> str:
    return f"checkpoint_{index_attempt_id}.json"


def save_checkpoint(
    db_session: Session, index_attempt_id: int, checkpoint: ConnectorCheckpoint
) -> str:
    """Save a checkpoint for a given index attempt to the file store"""
    checkpoint_pointer = _build_checkpoint_pointer(index_attempt_id)

    file_store = get_default_file_store(db_session)
    file_store.save_file(
        file_name=checkpoint_pointer,
        content=BytesIO(checkpoint.model_dump_json().encode()),
        display_name=checkpoint_pointer,
        file_origin=FileOrigin.INDEXING_CHECKPOINT,
        file_type="application/json",
    )

    index_attempt = get_index_attempt(db_session, index_attempt_id)
    if not index_attempt:
        raise RuntimeError(f"Index attempt {index_attempt_id} not found in DB.")
    index_attempt.checkpoint_pointer = checkpoint_pointer
    db_session.add(index_attempt)
    db_session.commit()
    return checkpoint_pointer


def load_checkpoint(
    db_session: Session, index_attempt_id: int
) -> ConnectorCheckpoint | None:
    """Load a checkpoint for a given index attempt from the file store"""
    checkpoint_pointer = _build_checkpoint_pointer(index_attempt_id)
    file_store = get_default_file_store(db_session)
    try:
        checkpoint_io = file_store.read_file(checkpoint_pointer, mode="rb")
        checkpoint_data = checkpoint_io.read().decode("utf-8")
        return ConnectorCheckpoint.model_validate_json(checkpoint_data)
    except RuntimeError:
        return None


def get_latest_valid_checkpoint(
    db_session: Session,
    cc_pair_id: int,
    search_settings_id: int,
    window_start: datetime,
    window_end: datetime,
) -> ConnectorCheckpoint:
    """Get the latest valid checkpoint for a given connector credential pair"""
    checkpoint_candidates = get_recent_completed_attempts_for_cc_pair(
        cc_pair_id=cc_pair_id,
        search_settings_id=search_settings_id,
        db_session=db_session,
        limit=_NUM_RECENT_ATTEMPTS_TO_CONSIDER,
    )
    checkpoint_candidates = [
        candidate
        for candidate in checkpoint_candidates
        if (
            candidate.poll_range_start == window_start
            and candidate.poll_range_end == window_end
            and candidate.status == IndexingStatus.FAILED
            and candidate.checkpoint_pointer is not None
            # we want to make sure that the checkpoint is actually useful
            # if it's only gone through a few docs, it's probably not worth
            # using. This also avoids weird cases where a connector is basically
            # non-functional but still "makes progress" by slowly moving the
            # checkpoint forward run after run
            and candidate.total_docs_indexed
            and candidate.total_docs_indexed > _NUM_DOCS_INDEXED_TO_BE_VALID_CHECKPOINT
        )
    ]

    # don't keep using checkpoints if we've had a bunch of failed attempts in a row
    # for now, capped at 10
    if len(checkpoint_candidates) == _NUM_RECENT_ATTEMPTS_TO_CONSIDER:
        logger.warning(
            f"{_NUM_RECENT_ATTEMPTS_TO_CONSIDER} consecutive failed attempts found "
            f"for cc_pair={cc_pair_id}. Ignoring checkpoint to let the run start "
            "from scratch."
        )
        return ConnectorCheckpoint.build_dummy_checkpoint()

    # assumes latest checkpoint is the furthest along. This only isn't true
    # if something else has gone wrong.
    latest_valid_checkpoint_candidate = (
        checkpoint_candidates[0] if checkpoint_candidates else None
    )

    checkpoint = ConnectorCheckpoint.build_dummy_checkpoint()
    if latest_valid_checkpoint_candidate:
        try:
            previous_checkpoint = load_checkpoint(
                db_session=db_session,
                index_attempt_id=latest_valid_checkpoint_candidate.id,
            )
        except Exception:
            logger.exception(
                f"Failed to load checkpoint from previous failed attempt with ID "
                f"{latest_valid_checkpoint_candidate.id}."
            )
            previous_checkpoint = None

        if previous_checkpoint is not None:
            logger.info(
                f"Using checkpoint from previous failed attempt with ID "
                f"{latest_valid_checkpoint_candidate.id}. Previous checkpoint: "
                f"{previous_checkpoint}"
            )
            save_checkpoint(
                db_session=db_session,
                index_attempt_id=latest_valid_checkpoint_candidate.id,
                checkpoint=previous_checkpoint,
            )
            checkpoint = previous_checkpoint

    return checkpoint


def get_index_attempts_with_old_checkpoints(
    db_session: Session, days_to_keep: int = 7
) -> list[IndexAttempt]:
    """Get all index attempts with checkpoints older than the specified number of days.

    Args:
        db_session: The database session
        days_to_keep: Number of days to keep checkpoints for (default: 7)

    Returns:
        Number of checkpoints deleted
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

    file_store = get_default_file_store(db_session)
    file_store.delete_file(index_attempt.checkpoint_pointer)

    index_attempt.checkpoint_pointer = None
    db_session.add(index_attempt)
    db_session.commit()

    return None


def check_checkpoint_size(checkpoint: ConnectorCheckpoint) -> None:
    """Check if the checkpoint content size exceeds the limit (200MB)"""
    content_size = deep_getsizeof(checkpoint.checkpoint_content)
    if content_size > 200_000_000:  # 200MB in bytes
        raise ValueError(
            f"Checkpoint content size ({content_size} bytes) exceeds 200MB limit"
        )
