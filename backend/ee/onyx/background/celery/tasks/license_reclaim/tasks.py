from datetime import datetime

import requests
from celery import shared_task

from ee.onyx.server.license.models import LicenseSource
from ee.onyx.utils.license import (
    AUTH_REJECTED_STATUSES,
    load_verified_license,
    reclaim_license_from_control_plane,
)
from ee.onyx.utils.license_expiry import (
    is_license_due_for_reclaim,
    is_license_reclaim_urgent,
    license_reclaim_interval,
)
from onyx.configs.app_configs import JOB_TIMEOUT
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.redis.redis_pool import get_redis_client
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()

# One key per tier, so a wide lead-up slot cannot span the approach to expiry
# where the tight interval belongs.
_THROTTLE_KEY_LEAD_UP = "license_reclaim_throttle"
_THROTTLE_KEY_URGENT = "license_reclaim_throttle_urgent"

# Consecutive attempts that found nothing newer. Outlives the throttle it sizes.
_IDLE_ROUNDS_KEY = "license_reclaim_idle_rounds"
_IDLE_ROUNDS_TTL_SEC = 24 * 60 * 60


def _idle_rounds() -> int:
    try:
        raw = get_redis_client().get(_IDLE_ROUNDS_KEY)
        return int(raw) if raw is not None else 0
    except Exception as e:
        logger.debug("License reclaim backoff state unavailable: %s", e)
        return 0


def _reclaim_slot_is_free(expires_at: datetime) -> bool:
    """Claim this tier's next attempt slot, sized by recent futility.

    Fails open: losing the throttle costs extra control-plane requests, and
    failing closed would strand a renewed customer on an expired license.
    """
    urgent = is_license_reclaim_urgent(expires_at)
    key = _THROTTLE_KEY_URGENT if urgent else _THROTTLE_KEY_LEAD_UP
    interval = int(license_reclaim_interval(expires_at, _idle_rounds()).total_seconds())
    try:
        return bool(get_redis_client().set(key, "1", nx=True, ex=interval))
    except Exception as e:
        logger.debug("License reclaim throttle unavailable: %s", e)
        return True


def _record_attempt(found_newer: bool) -> None:
    """Reset the backoff when something arrived, widen it when nothing did.

    Never raises: this only tunes a polling interval.
    """
    try:
        redis_client = get_redis_client()
        if found_newer:
            redis_client.delete(_IDLE_ROUNDS_KEY)
            return
        # One transaction: an INCR whose EXPIRE never lands leaves a counter
        # that outlives the lapse it was counting.
        pipe = redis_client.pipeline()
        pipe.incr(_IDLE_ROUNDS_KEY)
        pipe.expire(_IDLE_ROUNDS_KEY, _IDLE_ROUNDS_TTL_SEC)
        pipe.execute()
    except Exception as e:
        logger.debug("License reclaim backoff update failed: %s", e)


@shared_task(
    name=OnyxCeleryTask.RECLAIM_LICENSE,
    ignore_result=True,
    soft_time_limit=JOB_TIMEOUT,
)
def reclaim_license_task(*, tenant_id: str) -> None:  # noqa: ARG001
    if MULTI_TENANT:
        return

    with get_session_with_current_tenant() as db_session:
        # Gates below run on the signed blob, the only value that cannot lag
        # the row.
        try:
            stored = load_verified_license(db_session)
        except ValueError:
            logger.error("Stored license does not verify, skipping reclaim")
            return
        if stored is None:
            return
        payload = stored.payload

        # Sales-issued licenses are replaced by hand, nothing to fetch.
        if payload.source == LicenseSource.MANUAL_UPLOAD:
            return

        if not is_license_due_for_reclaim(payload.expires_at):
            return

        # Everything past here reaches the control plane.
        if not _reclaim_slot_is_free(payload.expires_at):
            return

        try:
            renewed = reclaim_license_from_control_plane(db_session)
        except (requests.RequestException, ValueError) as e:
            response = getattr(e, "response", None)
            status_code = response.status_code if response is not None else None
            if status_code in AUTH_REJECTED_STATUSES:
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
            # An unreachable control plane is also a reason to ease off.
            _record_attempt(found_newer=False)
            return

        if renewed is None:
            logger.warning(
                "Skipped license reclaim for tenant %s: no usable stored license, "
                "or it was already rejected by the control plane",
                payload.tenant_id,
            )
            _record_attempt(found_newer=False)
            return

        # The payload comes back either way, so the issue date marks a real renewal.
        found_newer = renewed.issued_at > payload.issued_at
        _record_attempt(found_newer=found_newer)
        if not found_newer:
            return

        logger.info(
            "License reclaimed: seats=%s, expires=%s",
            renewed.seats,
            renewed.expires_at.date(),
        )
