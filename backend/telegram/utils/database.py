from contextlib import contextmanager
from typing import Callable, Any, Generator

from sqlalchemy.orm import Session

from onyx.db.engine import get_sqlalchemy_engine


@contextmanager
def get_session() -> Generator[Session, Any, None]:
    with Session(get_sqlalchemy_engine(), expire_on_commit=False) as session:
        yield session



def with_session(handler: Callable):
    def wrapper(message, state: None = None):
        with get_session() as session:
            return handler(message, session, state)
    return wrapper
