from sqlalchemy.orm import Session

from onyx.db.models import BackgroundErrors


def create_background_error(db_session: Session, message: str) -> None:
    db_session.add(BackgroundErrors(message=message))
    db_session.commit()
