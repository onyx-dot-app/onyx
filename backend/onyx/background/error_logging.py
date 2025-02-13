from onyx.background.celery.apps.app_base import task_logger
from onyx.db.background_error import create_background_error
from onyx.db.engine import get_session_with_tenant


def emit_background_error(
    message: str,
    cc_pair_id: int | None = None,
    skip_log: bool = False,
) -> None:
    """Currently just saves a row in the background_errors table + logs error.

    In the future, could create notifications based on the severity."""
    with get_session_with_tenant() as db_session:
        create_background_error(db_session, message, cc_pair_id)

    if not skip_log:
        # use task_logger since this is assumed to be called from worker
        task_logger.error(message)
