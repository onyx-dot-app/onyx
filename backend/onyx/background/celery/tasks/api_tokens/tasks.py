from datetime import datetime, timedelta, timezone

from celery import shared_task

from onyx.background.celery.apps.app_base import task_logger
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.api_token import delete_orphaned_api_tokens
from onyx.db.engine.sql_engine import get_session_with_current_tenant

# Long past any in-flight request, so a token a save is still writing is
# never taken for an orphan.
ORPHAN_GRACE_PERIOD = timedelta(hours=1)


@shared_task(
    name=OnyxCeleryTask.CLEANUP_ORPHANED_API_TOKENS, ignore_result=True, trail=False
)
def cleanup_orphaned_api_tokens(*, tenant_id: str) -> None:
    """Deletes API tokens that no feature uses anymore."""
    with get_session_with_current_tenant() as db_session:
        deleted = delete_orphaned_api_tokens(
            db_session,
            unused_since=datetime.now(timezone.utc) - ORPHAN_GRACE_PERIOD,
        )
    if deleted:
        task_logger.info(
            f"Deleted {deleted} orphaned API token(s) (tenant {tenant_id})."
        )
