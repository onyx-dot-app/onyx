from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.file_store.file_store import get_default_file_store
from tests.external_dependency_unit.connectors.file.file_edit_helpers import (
    FilePair,
    staged_file_ids,
)
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)


@pytest.fixture
def file_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    initialize_file_store: None,  # noqa: ARG001
) -> Generator[FilePair, None, None]:
    file_pair = FilePair(make_cc_pair(db_session, source=DocumentSource.FILE))
    yield file_pair
    db_session.rollback()
    file_store = get_default_file_store()
    for file_id in {
        *file_pair.file_ids,
        *staged_file_ids(db_session, file_pair.pair.id),
    }:
        file_store.delete_file(file_id, error_on_missing=False)
    cleanup_cc_pair(db_session, file_pair.pair)
