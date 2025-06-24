from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session


def get_db_current_time(db_session: Session) -> datetime:
    result = db_session.execute(text("SELECT NOW()")).scalar()
    if result is None:
        raise ValueError("Database did not return a time")
    return result
