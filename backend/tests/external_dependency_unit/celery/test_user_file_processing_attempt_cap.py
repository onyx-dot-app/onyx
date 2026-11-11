"""A user file is marked FAILED after USER_FILE_PROCESSING_MAX_ATTEMPTS pickups,
even when each worker dies mid-file where no except clause runs."""

from unittest.mock import patch

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.user_file_processing.tasks import (
    process_user_file_impl,
)
from onyx.configs.constants import USER_FILE_PROCESSING_MAX_ATTEMPTS
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import UserFileStatus
from onyx.db.models import UserFile
from onyx.db.user_file import consume_user_file_processing_attempt
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.conftest import (
    create_processing_user_file,
    create_test_user,
    delete_test_user,
)

_LOAD_DOCUMENTS = (
    "onyx.background.celery.tasks.user_file_processing.tasks._load_user_file_documents"
)


def _pickup_then_die(user_file_id: str) -> None:
    # SystemExit is not an Exception, so like a kernel kill it skips the FAILED
    # marking in the task's except clauses.
    with (
        patch(_LOAD_DOCUMENTS, side_effect=SystemExit),
        pytest.raises(SystemExit),
    ):
        process_user_file_impl(
            user_file_id=user_file_id,
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
            redis_locking=False,
        )


def test_file_fails_after_max_pickups(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    user = create_test_user(db_session, "attempt_cap_user")
    uf = create_processing_user_file(db_session, user.id)
    try:
        for pickup in range(1, USER_FILE_PROCESSING_MAX_ATTEMPTS + 1):
            _pickup_then_die(str(uf.id))
            db_session.refresh(uf)
            assert uf.processing_attempts == pickup
            assert uf.status == UserFileStatus.PROCESSING

        with patch(_LOAD_DOCUMENTS) as load_documents:
            process_user_file_impl(
                user_file_id=str(uf.id),
                tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
                redis_locking=False,
            )

        load_documents.assert_not_called()
        db_session.refresh(uf)
        assert uf.status == UserFileStatus.FAILED
        assert uf.processing_attempts == USER_FILE_PROCESSING_MAX_ATTEMPTS + 1
    finally:
        db_session.delete(uf)
        db_session.commit()
        delete_test_user(db_session, user)


def test_exhausted_pickup_keeps_a_concurrent_delete(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    user = create_test_user(db_session, "attempt_cap_delete_user")
    uf = create_processing_user_file(db_session, user.id)
    try:
        uf.processing_attempts = USER_FILE_PROCESSING_MAX_ATTEMPTS
        db_session.commit()
        db_session.refresh(uf)

        # The delete lands in another session after the worker read PROCESSING,
        # so the worker's row object is stale when it spends the attempt.
        with get_session_with_current_tenant() as other_session:
            other_session.execute(
                update(UserFile)
                .where(UserFile.id == uf.id)
                .values(status=UserFileStatus.DELETING)
            )
            other_session.commit()
        assert uf.status == UserFileStatus.PROCESSING

        assert consume_user_file_processing_attempt(db_session, uf) is False

        db_session.refresh(uf)
        assert uf.status == UserFileStatus.DELETING
        assert uf.processing_attempts == USER_FILE_PROCESSING_MAX_ATTEMPTS + 1
    finally:
        db_session.delete(uf)
        db_session.commit()
        delete_test_user(db_session, user)
