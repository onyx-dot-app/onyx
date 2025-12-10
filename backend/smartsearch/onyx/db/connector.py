from sqlalchemy import distinct
from sqlalchemy.orm import Session
from onyx.configs.constants import DocumentSource
from onyx.db.models import Connector
from onyx.utils.logger import setup_logger

logger = setup_logger()

def fetch_sources_with_connectors(db_session: Session) -> list[DocumentSource]:
    """
    Извлекает уникальные источники документов, для которых существуют коннекторы.
    """
    query_results = db_session.query(distinct(Connector.source)).all()  # type: ignore
    unique_sources: list[DocumentSource] = []
    index = 0
    while index < len(query_results):
        unique_sources.append(query_results[index][0])
        index += 1

    return unique_sources
