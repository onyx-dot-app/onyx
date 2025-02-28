from sqlalchemy.exc import IntegrityError

from onyx.db.background_error import create_background_error
from onyx.db.session import get_session_with_current_tenant


def emit_background_error(
    message: str,
    cc_pair_id: int | None = None,
) -> None:
    """Currently just saves a row in the background_errors table.

    In the future, could create notifications based on the severity."""
    with get_session_with_current_tenant() as db_session:
        try:
            create_background_error(db_session, message, cc_pair_id)
        except IntegrityError as e:
            # Log an error if the cc_pair_id was deleted or any other exception occurs
            error_message = f"Failed to create background error: {str(e)}. Original message: {message}"
            create_background_error(db_session, error_message, None)
