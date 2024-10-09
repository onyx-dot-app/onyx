import abc
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from danswer.db.index_attempt import get_index_attempt
from danswer.utils.logger import setup_logger

logger = setup_logger()


class Heartbeat(abc.ABC):
    """Useful for any long-running work that goes through a bunch of items
    and needs to occasionally give updates on progress.
    e.g. chunking, embedding, updating vespa, etc."""

    @abc.abstractmethod
    def heartbeat(self, metadata: Any = None) -> None:
        raise NotImplementedError


class IndexingHeartbeat(Heartbeat):
    def __init__(self, index_attempt_id: int, db_session: Session, freq: int):
        self.cnt = 0

        self.index_attempt_id = index_attempt_id
        self.db_session = db_session
        self.freq = freq

    def heartbeat(self, metadata: Any = None) -> None:
        self.cnt += 1
        if self.cnt % self.freq == 0:
            index_attempt = get_index_attempt(
                db_session=self.db_session, index_attempt_id=self.index_attempt_id
            )
            if index_attempt:
                index_attempt.time_updated = func.now()
                self.db_session.commit()
            else:
                logger.error("Index attempt not found, this should not happen!")
