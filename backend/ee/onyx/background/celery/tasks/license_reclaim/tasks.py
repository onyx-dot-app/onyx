import requests
from celery import shared_task

from ee.onyx.db.license import get_license_metadata
from ee.onyx.utils.license import (
    block_license_reclaim,
    license_reclaim_is_blocked,
    reclaim_license_from_control_plane,
)
from ee.onyx.utils.license_expiry import is_license_due_for_reclaim
from onyx.configs.app_configs import JOB_TIMEOUT
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()

# The control plane rejects the stored license as a credential under these.
_AUTH_REJECTED_STATUSES = frozenset({401, 403})


@shared_task(
    name=OnyxCeleryTask.RECLAIM_LICENSE,
    ignore_result=True,
    soft_time_limit=JOB_TIMEOUT,
)
def reclaim_license_task(*, tenant_id: str) -> None:  # noqa: ARG001
    if MULTI_TENANT:
        return

    with get_session_with_current_tenant() as db_session:
        metadata = get_license_metadata(db_session)
        if not metadata:
            return

        if not is_license_due_for_reclaim(metadata.expires_at):
            return

        if license_reclaim_is_blocked(metadata.tenant_id):
            return

        try:
            renewed = reclaim_license_from_control_plane(db_session)
        except requests.HTTPError as e:
            status_code = e.response.status_code if e.response is not None else None
            if status_code in _AUTH_REJECTED_STATUSES:
                # The stored license IS the credential, so retrying it can only
                # fail the same way. Stop until a new license is installed.
                block_license_reclaim(metadata.tenant_id)
                logger.error(
                    "License reclaim rejected for tenant %s (HTTP %s). The stored "
                    "license is not accepted by the control plane and must be "
                    "replaced before renewals can resume.",
                    metadata.tenant_id,
                    status_code,
                )
                return
            logger.warning(
                "Failed to reclaim license for tenant %s: %s", metadata.tenant_id, e
            )
            return
        except (requests.RequestException, ValueError) as e:
            # A transient outage or a malformed response retries next run.
            logger.warning(
                "Failed to reclaim license for tenant %s: %s", metadata.tenant_id, e
            )
            return

        if renewed is None:
            logger.warning(
                "Skipped license reclaim for tenant %s: no license metadata to "
                "authenticate with",
                metadata.tenant_id,
            )
            return

        logger.info(
            "License reclaimed: seats=%s, expires=%s",
            renewed.seats,
            renewed.expires_at.date(),
        )
