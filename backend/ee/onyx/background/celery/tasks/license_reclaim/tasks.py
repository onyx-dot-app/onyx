from datetime import datetime, timedelta, timezone

import requests
from celery import shared_task

from ee.onyx.db.license import get_license_metadata
from ee.onyx.utils.license import reclaim_license_from_control_plane
from onyx.configs.app_configs import JOB_TIMEOUT
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()

LICENSE_RECLAIM_WINDOW = timedelta(days=7)


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

        # Licenses past the grace window must still be re-claimed, so gate on
        # expires_at, not get_expiry_warning_stage (its NONE covers that case too).
        if metadata.expires_at - datetime.now(timezone.utc) > LICENSE_RECLAIM_WINDOW:
            return

        try:
            renewed = reclaim_license_from_control_plane(db_session)
        except requests.RequestException as e:
            # A transient control-plane outage is expected. The next run retries.
            logger.warning(
                "Failed to reclaim license for tenant %s: %s", metadata.tenant_id, e
            )
            return
        except ValueError as e:
            logger.warning(
                "Control plane returned invalid license for tenant %s: %s",
                metadata.tenant_id,
                e,
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
