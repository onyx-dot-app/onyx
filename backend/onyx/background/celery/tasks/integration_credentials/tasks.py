from celery import shared_task

from onyx.background.celery.tasks.beat_schedule import BEAT_EXPIRES_DEFAULT
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.integrations.connections import credential_import_done
from onyx.integrations.credential_import import run_credential_import_if_needed


@shared_task(
    name=OnyxCeleryTask.IMPORT_INTEGRATION_CREDENTIALS,
    ignore_result=True,
    trail=False,
    expires=BEAT_EXPIRES_DEFAULT,
)
def import_integration_credentials(*, tenant_id: str) -> None:  # noqa: ARG001
    """Move the tenant's old credentials into the integration tables once."""
    if credential_import_done():
        return
    with get_session_with_current_tenant() as db_session:
        run_credential_import_if_needed(db_session)
