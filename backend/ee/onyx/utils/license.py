"""License signature verification, persistence, and control-plane re-claim."""

import base64
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from ee.onyx.configs.app_configs import CLOUD_DATA_PLANE_URL
from ee.onyx.server.license.models import (
    LicenseData,
    LicenseMetadata,
    LicensePayload,
    LicenseSource,
)
from onyx.server.settings.models import ApplicationStatus
from onyx.utils.logger import setup_logger

logger = setup_logger()

# A license inside this window (or already expired) is due for re-claim from
# the control plane. Shared by the beat backstop and the point-of-use trigger.
LICENSE_RECLAIM_WINDOW = timedelta(days=7)

# One reclaim attempt per debounce period, no matter how many requests see a
# stale license. Redis key TTL is the debounce.
_LICENSE_RECLAIM_DEBOUNCE_KEY = "license_reclaim_debounce"
_LICENSE_RECLAIM_DEBOUNCE_TTL_SEC = 15 * 60

# Path to the license public key file
_LICENSE_PUBLIC_KEY_PATH = (
    Path(__file__).parent.parent.parent.parent / "keys" / "license_public_key.pem"
)


class ControlPlaneLicenseResponse(BaseModel):
    license: str


def _get_public_key() -> RSAPublicKey:
    """Load the public key from file, with env var override."""
    # Allow env var override for flexibility
    key_pem = os.environ.get("LICENSE_PUBLIC_KEY_PEM")

    if not key_pem:
        # Read from file
        if not _LICENSE_PUBLIC_KEY_PATH.exists():
            raise ValueError(
                f"License public key not found at {_LICENSE_PUBLIC_KEY_PATH}. "
                "License verification requires the control plane public key."
            )
        key_pem = _LICENSE_PUBLIC_KEY_PATH.read_text()

    key = serialization.load_pem_public_key(key_pem.encode())
    if not isinstance(key, RSAPublicKey):
        raise ValueError("Expected RSA public key")
    return key


def verify_license_signature(license_data: str) -> LicensePayload:
    """
    Verify RSA-4096 signature and return payload if valid.

    Args:
        license_data: Base64-encoded JSON containing payload and signature

    Returns:
        LicensePayload if signature is valid

    Raises:
        ValueError: If license data is invalid or signature verification fails
    """
    try:
        decoded = json.loads(base64.b64decode(license_data))

        # Parse into LicenseData to validate structure
        license_obj = LicenseData(**decoded)

        # IMPORTANT: Use the ORIGINAL payload JSON for signature verification,
        # not re-serialized through Pydantic. Pydantic may format fields differently
        # (e.g., datetime "+00:00" vs "Z") which would break signature verification.
        original_payload = decoded.get("payload", {})
        payload_json = json.dumps(original_payload, sort_keys=True)
        signature_bytes = base64.b64decode(license_obj.signature)

        # Verify signature using PSS padding (modern standard)
        public_key = _get_public_key()

        public_key.verify(
            signature_bytes,
            payload_json.encode(),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )

        return license_obj.payload

    except InvalidSignature:
        logger.error("[verify_license] FAILED: Signature verification failed")
        raise ValueError("Invalid license signature")
    except json.JSONDecodeError as e:
        logger.error("[verify_license] FAILED: JSON decode error: %s", e)
        raise ValueError("Invalid license format: not valid JSON")
    except (ValueError, KeyError, TypeError) as e:
        logger.error(
            "[verify_license] FAILED: Validation error: %s: %s", type(e).__name__, e
        )
        raise ValueError(f"Invalid license format: {type(e).__name__}: {e}")
    except Exception:
        logger.exception("[verify_license] FAILED: Unexpected error")
        raise ValueError("License verification failed: unexpected error")


def verify_and_store_license(
    db_session: Session,
    license_data: str,
    *,
    source: LicenseSource,
) -> LicensePayload:
    """Persist a license blob only after its signature verifies.

    Raises ValueError on an unverifiable blob, leaving the stored license untouched.
    """
    # Keep the utils -> db dependency call-time only so db/license.py can
    # import this module at top level.
    from ee.onyx.db.license import update_license_cache, upsert_license

    payload = verify_license_signature(license_data)
    upsert_license(db_session, license_data)

    # The cache is derived state that self-heals on the next read, so a cache
    # outage must not discard a license that is already persisted.
    try:
        update_license_cache(payload, source=source)
    except Exception as cache_error:
        logger.warning("Failed to update license cache: %s", cache_error)

    return payload


def reclaim_license_from_control_plane(db_session: Session) -> LicensePayload | None:
    """Re-fetch this instance's license from the control plane, authenticating with the stored one.

    Returns None when no usable stored license exists to authenticate with.
    Raises ValueError when the control plane response has no valid license.
    """
    # Keep the utils -> db dependency call-time only so db/license.py can
    # import this module at top level.
    from ee.onyx.db.license import get_license, get_license_metadata

    metadata = get_license_metadata(db_session)
    if not metadata or not metadata.tenant_id:
        return None

    license_row = get_license(db_session)
    if not license_row or not license_row.license_data:
        return None

    response = requests.get(
        f"{CLOUD_DATA_PLANE_URL}/proxy/license/{metadata.tenant_id}",
        headers={
            "Authorization": f"Bearer {license_row.license_data}",
            "Content-Type": "application/json",
        },
        timeout=30,
    )
    response.raise_for_status()

    try:
        response_data = ControlPlaneLicenseResponse.model_validate(response.json())
    except ValidationError as e:
        raise ValueError("No license in response") from e

    return verify_and_store_license(
        db_session, response_data.license, source=LicenseSource.AUTO_FETCH
    )


def maybe_schedule_license_reclaim(metadata: LicenseMetadata, tenant_id: str) -> None:
    """Enqueue an immediate license re-claim when the stored license is due.

    Point-of-use companion to the beat backstop: any request that observes a
    license expired or expiring within LICENSE_RECLAIM_WINDOW triggers one
    reclaim attempt per debounce period. Never raises, since a scheduling
    failure must not affect the request that tripped it.
    """
    # Call-time imports: this runs inside request middleware, and the celery
    # client / redis pool must not become import-time dependencies of every
    # consumer of this module.
    from onyx.background.celery.versioned_apps.client import app as client_app
    from onyx.configs.constants import OnyxCeleryPriority, OnyxCeleryTask
    from onyx.redis.redis_pool import get_redis_client

    try:
        if metadata.expires_at - datetime.now(timezone.utc) > LICENSE_RECLAIM_WINDOW:
            return

        redis_client = get_redis_client(tenant_id=tenant_id)
        # SET NX doubles as the debounce and a cross-process lock: only the
        # first request in the window enqueues.
        if not redis_client.set(
            _LICENSE_RECLAIM_DEBOUNCE_KEY,
            "1",
            nx=True,
            ex=_LICENSE_RECLAIM_DEBOUNCE_TTL_SEC,
        ):
            return

        client_app.send_task(
            OnyxCeleryTask.RECLAIM_LICENSE,
            kwargs={"tenant_id": tenant_id},
            priority=OnyxCeleryPriority.HIGH,
            expires=_LICENSE_RECLAIM_DEBOUNCE_TTL_SEC,
        )
        logger.info(
            "Scheduled license reclaim (license expires %s)",
            metadata.expires_at.date(),
        )
    except Exception as e:
        logger.warning("Failed to schedule license reclaim: %s", e)


def get_license_status(
    payload: LicensePayload,
    grace_period_end: datetime | None = None,
) -> ApplicationStatus:
    """
    Determine current license status based on expiry.

    Args:
        payload: The verified license payload
        grace_period_end: Optional grace period end datetime

    Returns:
        ApplicationStatus indicating current license state
    """
    now = datetime.now(timezone.utc)

    # Check if grace period has expired
    if grace_period_end and now > grace_period_end:
        return ApplicationStatus.GATED_ACCESS

    # Check if license has expired
    if now > payload.expires_at:
        if grace_period_end and now <= grace_period_end:
            return ApplicationStatus.GRACE_PERIOD
        return ApplicationStatus.GATED_ACCESS

    # License is valid
    return ApplicationStatus.ACTIVE


def is_license_valid(payload: LicensePayload) -> bool:
    """Check if a license is currently valid (not expired)."""
    now = datetime.now(timezone.utc)
    return now <= payload.expires_at
