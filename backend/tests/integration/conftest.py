from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session

from danswer.db.embedding_model import get_current_db_embedding_model
from danswer.db.engine import get_session_context_manager
from tests.integration.common_utils.reset import reset_all
from tests.integration.common_utils.vespa import TestVespaClient


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    with get_session_context_manager() as session:
        yield session


@pytest.fixture
def vespa_client(db_session: Session) -> TestVespaClient:
    current_model = get_current_db_embedding_model(db_session)
    return TestVespaClient(index_name=current_model.index_name)


@pytest.fixture
def reset() -> None:
    reset_all()
