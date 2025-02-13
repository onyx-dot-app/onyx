from sqlalchemy.orm import Session

from onyx.db.engine import get_session_with_tenant
from onyx.db.models import BackgroundErrors


def _create_background_error(db_session: Session, message: str) -> None:
    db_session.add(BackgroundErrors(message=message))
    db_session.commit()


def create_background_error(message: str, db_session: Session | None = None) -> None:
    if db_session is None:
        with get_session_with_tenant() as db_session:
            _create_background_error(db_session, message)
    else:
        _create_background_error(db_session, message)
