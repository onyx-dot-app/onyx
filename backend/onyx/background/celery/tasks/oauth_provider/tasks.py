from datetime import datetime, timezone

from celery import shared_task

from onyx.configs.constants import OnyxCeleryTask
from onyx.db.engine.sql_engine import (
    get_catalog_session,
    get_session_with_current_tenant,
)
from onyx.db.oauth_provider import (
    delete_expired_oauth_provider_grants__no_commit,
    delete_idle_oauth_provider_clients__no_commit,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


@shared_task(
    name=OnyxCeleryTask.CLEANUP_OAUTH_PROVIDER_GRANTS, ignore_result=True, trail=False
)
def cleanup_oauth_provider_grants(*, tenant_id: str) -> None:  # noqa: ARG001
    with get_session_with_current_tenant() as db_session:
        deleted: int = delete_expired_oauth_provider_grants__no_commit(
            db_session, now=datetime.now(timezone.utc)
        )
        db_session.commit()
    if deleted:
        logger.info("Deleted %s expired OAuth provider grant(s)", deleted)


@shared_task(
    name=OnyxCeleryTask.CLEANUP_OAUTH_PROVIDER_CLIENTS, ignore_result=True, trail=False
)
def cleanup_oauth_provider_clients(*, tenant_id: str | None = None) -> None:  # noqa: ARG001
    with get_catalog_session() as db_session:
        deleted: int = delete_idle_oauth_provider_clients__no_commit(
            db_session, now=datetime.now(timezone.utc)
        )
        db_session.commit()
    if deleted:
        logger.info("Deleted %s idle OAuth provider client(s)", deleted)
