from sqlalchemy.orm import Session

from onyx.db.models import BackgroundError


def create_background_error(
    db_session: Session, message: str, cc_pair_id: int | None
) -> None:
    db_session.add(BackgroundError(message=message, cc_pair_id=cc_pair_id))
    db_session.commit()
