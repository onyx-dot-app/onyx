import time
from datetime import datetime, timezone

from celery import shared_task
from psycopg2.errors import UndefinedTable
from sqlalchemy.exc import ProgrammingError

from onyx.configs.constants import OnyxCeleryTask
from onyx.db.engine.sql_engine import (
    get_catalog_session,
    get_session_with_current_tenant,
)
from onyx.db.oauth_provider import (
    cleanup_oauth_provider_clients__no_commit,
    cleanup_oauth_provider_grants__no_commit,
    cleanup_oauth_provider_tokens__no_commit,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()
_BATCH_SIZE = 1000
_MAX_BATCHES = 100
_WORK_BUDGET_SECONDS = 60


def _run_cleanup(*, catalog: bool) -> int:
    session_factory = (
        get_catalog_session if catalog else get_session_with_current_tenant
    )
    operations = (
        (cleanup_oauth_provider_clients__no_commit,)
        if catalog
        else (
            cleanup_oauth_provider_tokens__no_commit,
            cleanup_oauth_provider_grants__no_commit,
        )
    )
    deadline = time.monotonic() + _WORK_BUDGET_SECONDS
    now = datetime.now(timezone.utc)
    deleted = 0
    for _ in range(_MAX_BATCHES):
        if time.monotonic() >= deadline:
            break
        try:
            with session_factory() as session:
                batch_deleted = sum(
                    operation(session, now=now, batch_size=_BATCH_SIZE)
                    for operation in operations
                )
                session.commit()
        except ProgrammingError as error:
            if not isinstance(error.orig, UndefinedTable):
                raise
            logger.info("OAuth provider cleanup skipped pending database migration")
            return deleted
        deleted += batch_deleted
        if batch_deleted == 0:
            break
    logger.info("OAuth provider cleanup deleted %s rows; catalog=%s", deleted, catalog)
    return deleted


@shared_task(name=OnyxCeleryTask.CLEANUP_OAUTH_PROVIDER_RECORDS, ignore_result=True)
def cleanup_oauth_provider_records(*, tenant_id: str) -> int:  # noqa: ARG001
    return _run_cleanup(catalog=False)


@shared_task(name=OnyxCeleryTask.CLEANUP_OAUTH_PROVIDER_CLIENTS, ignore_result=True)
def cleanup_oauth_provider_clients(*, tenant_id: str | None = None) -> int:  # noqa: ARG001
    return _run_cleanup(catalog=True)
