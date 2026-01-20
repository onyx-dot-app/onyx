"""License refresh Celery task.

Runs daily to refresh the license from the control plane and update the cache.
For self-hosted deployments, this keeps the license fresh without manual intervention.
"""

import requests
from celery import shared_task

from ee.onyx.db.license import refresh_license_cache
from ee.onyx.db.license import update_license_cache
from ee.onyx.db.license import upsert_license
from ee.onyx.server.license.models import LicenseSource
from ee.onyx.server.tenants.access import generate_data_plane_token
from ee.onyx.utils.license import verify_license_signature
from onyx.background.celery.apps.app_base import task_logger
from onyx.configs.app_configs import CONTROL_PLANE_API_BASE_URL
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from shared_configs.contextvars import get_current_tenant_id


@shared_task(
    name=OnyxCeleryTask.LICENSE_REFRESH_TASK,
    soft_time_limit=60,  # 1 minute
    time_limit=120,  # 2 minutes hard limit
    ignore_result=True,
    trail=False,
)
def license_refresh_task(tenant_id: str | None = None) -> bool:
    """
    Daily task to refresh license from control plane.

    This task:
    1. Tries to fetch a fresh license from the control plane
    2. On success: verifies, persists to DB, and updates cache
    3. On failure: logs warning, uses existing cached/DB license

    The license remains valid based on its `expires_at` field even if
    we can't reach the control plane. This allows air-gapped deployments
    to continue operating.

    Args:
        tenant_id: The tenant ID (for multi-tenant, passed via cloud_beat_task_generator)

    Returns:
        True if license was refreshed, False if using existing license
    """
    effective_tenant_id = tenant_id or get_current_tenant_id()

    task_logger.info(f"Starting license refresh for tenant {effective_tenant_id}")

    try:
        # Generate auth token for control plane
        token = generate_data_plane_token()
    except ValueError as e:
        task_logger.warning(
            f"Cannot refresh license - DATA_PLANE_SECRET not configured: {e}"
        )
        # Fall back to refreshing cache from database
        _refresh_from_database(effective_tenant_id)
        return False

    # Try to fetch fresh license from control plane
    try:
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        url = f"{CONTROL_PLANE_API_BASE_URL}/license/{effective_tenant_id}"

        task_logger.info(f"Fetching license from {url}")
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        data = response.json()
        if not isinstance(data, dict) or "license" not in data:
            task_logger.warning("Invalid response from control plane - missing license")
            _refresh_from_database(effective_tenant_id)
            return False

        license_data = data["license"]
        if not license_data:
            task_logger.info("No license returned from control plane")
            _refresh_from_database(effective_tenant_id)
            return False

        # Verify signature before persisting
        payload = verify_license_signature(license_data)

        # Verify the fetched license is for this tenant
        if payload.tenant_id != effective_tenant_id:
            task_logger.error(
                f"License tenant mismatch: expected {effective_tenant_id}, "
                f"got {payload.tenant_id}"
            )
            _refresh_from_database(effective_tenant_id)
            return False

        # Persist to DB and update cache
        with get_session_with_current_tenant() as db_session:
            upsert_license(db_session, license_data)

        update_license_cache(payload, source=LicenseSource.AUTO_FETCH)

        task_logger.info(
            f"License refreshed successfully: {payload.seats} seats, "
            f"expires {payload.expires_at.date()}"
        )
        return True

    except requests.HTTPError as e:
        status_code = e.response.status_code if e.response is not None else 0
        task_logger.warning(
            f"Control plane returned error {status_code} during license refresh"
        )
        _refresh_from_database(effective_tenant_id)
        return False

    except requests.RequestException as e:
        task_logger.warning(
            f"Cannot reach control plane for license refresh: {e}. "
            "Using existing license."
        )
        _refresh_from_database(effective_tenant_id)
        return False

    except ValueError as e:
        task_logger.error(f"License verification failed during refresh: {e}")
        _refresh_from_database(effective_tenant_id)
        return False

    except Exception as e:
        task_logger.exception(f"Unexpected error during license refresh: {e}")
        _refresh_from_database(effective_tenant_id)
        return False


def _refresh_from_database(tenant_id: str | None = None) -> None:
    """
    Refresh the license cache from the database.

    This is a fallback when we can't reach the control plane.
    The existing license in the database remains valid.
    """
    try:
        with get_session_with_current_tenant() as db_session:
            metadata = refresh_license_cache(db_session, tenant_id)
            if metadata:
                task_logger.info(
                    f"License cache refreshed from database: "
                    f"{metadata.seats} seats, status={metadata.status.value}"
                )
            else:
                task_logger.info("No license found in database")
    except Exception as e:
        task_logger.warning(f"Failed to refresh license cache from database: {e}")
