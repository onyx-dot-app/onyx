from onyx.db.background_error import create_background_error
from onyx.db.engine import get_session_with_tenant
from onyx.utils.logger import setup_logger


logger = setup_logger()


def emit_background_error(message: str, skip_log: bool = False) -> None:
    """Currently just saves a row in the background_errors table + logs error.

    In the future, could create notifications based on the severity."""
    with get_session_with_tenant() as db_session:
        create_background_error(db_session, message)

    if not skip_log:
        logger.error(message)
