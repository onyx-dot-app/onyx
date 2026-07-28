import requests
from celery import shared_task

from ee.onyx.db.license import get_license
from ee.onyx.server.license.models import LicenseSource
from ee.onyx.utils.license import (
    block_license_reclaim,
    license_reclaim_is_blocked,
    reclaim_license_from_control_plane,
    verify_license_signature,
)
from ee.onyx.utils.license_expiry import is_license_due_for_reclaim
from onyx.configs.app_configs import JOB_TIMEOUT
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()

# The stored license IS the credential for a re-claim, so a rejection under
# these can only repeat. Retrying it is wasted until a new license arrives.
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
        license_row = get_license(db_session)
        if not license_row or not license_row.license_data:
            return

        # Gate on the stored blob: a stale cache entry can misreport source
        # and expiry.
        try:
            payload = verify_license_signature(license_row.license_data)
        except ValueError:
            logger.error("Stored license does not verify, skipping reclaim")
            return

        # Sales-issued licenses are replaced by hand, nothing to fetch.
        if payload.source == LicenseSource.MANUAL_UPLOAD:
            return

        if not is_license_due_for_reclaim(payload.expires_at):
            return

        # A blocked enqueue is a cheap local no-op once per debounce window.
        if license_reclaim_is_blocked(license_row.license_data):
            return

        try:
            renewed = reclaim_license_from_control_plane(db_session)
        except (requests.RequestException, ValueError) as e:
            response = getattr(e, "response", None)
            status_code = response.status_code if response is not None else None
            if status_code in _AUTH_REJECTED_STATUSES:
                # A slow rejection may lose to a replacement install. Only the
                # blob still stored may be blocked, or a mismatched fingerprint
                # would burn an attempt for the current license.
                current = get_license(db_session)
                if not current or current.license_data != license_row.license_data:
                    return
                block_license_reclaim(license_row.license_data)
                logger.error(
                    "License reclaim rejected for tenant %s (HTTP %s). The stored "
                    "license is not accepted by the control plane and must be "
                    "replaced before renewals can resume.",
                    payload.tenant_id,
                    status_code,
                )
            else:
                # A transient outage or a malformed response retries next run.
                logger.warning(
                    "Failed to reclaim license for tenant %s: %s", payload.tenant_id, e
                )
            return

        if renewed is None:
            logger.warning(
                "Skipped license reclaim for tenant %s: the stored license blob is "
                "gone while its metadata is still cached",
                payload.tenant_id,
            )
            return

        logger.info(
            "License reclaimed: seats=%s, expires=%s",
            renewed.seats,
            renewed.expires_at.date(),
        )
