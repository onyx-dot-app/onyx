"""License signature verification, persistence, and control-plane re-claim."""

import base64
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

import requests
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from sqlalchemy.orm import Session

from ee.onyx.configs.app_configs import CLOUD_DATA_PLANE_URL
from ee.onyx.server.license.models import LicenseData, LicensePayload
from ee.onyx.utils.license_expiry import is_license_due_for_reclaim
from onyx.background.celery.versioned_apps.client import app as client_app
from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheBackendType
from onyx.configs.app_configs import CACHE_BACKEND
from onyx.configs.constants import OnyxCeleryPriority, OnyxCeleryTask
from onyx.redis.redis_pool import get_redis_client
from onyx.server.settings.models import ApplicationStatus
from onyx.utils.logger import setup_logger

logger = setup_logger()

# One reclaim attempt per debounce period, no matter how many requests see a
# stale license. Redis key TTL is the debounce. Redis rather than the cache
# backend, since what it debounces is a send onto the same broker.
_LICENSE_RECLAIM_DEBOUNCE_KEY = "license_reclaim_debounce"
_LICENSE_RECLAIM_DEBOUNCE_TTL_SEC = 15 * 60

# The control plane authenticates a re-claim with the stored license itself, so
# a rejected license cannot be fixed by retrying it. Back off for a day, or
# until a replacement license is stored, instead of every debounce period.
_LICENSE_RECLAIM_BLOCKED_KEY = "license_reclaim_blocked"
_LICENSE_RECLAIM_BLOCKED_TTL_SEC = 24 * 60 * 60

# Statuses meaning the stored license itself was refused, not a transient fault.
AUTH_REJECTED_STATUSES = frozenset({401, 403})

# Path to the license public key file
_LICENSE_PUBLIC_KEY_PATH = (
    Path(__file__).parent.parent.parent.parent / "keys" / "license_public_key.pem"
)


def license_from_control_plane_response(response: requests.Response) -> str:
    """Pull the signed blob out of a control-plane license response.

    Every malformed shape raises ValueError, which callers already treat as a
    retryable upstream fault. An empty string counts as absent rather than
    reaching signature verification and failing as a corrupt license.
    """
    try:
        body = response.json()
    except ValueError as e:
        raise ValueError("Control plane response was not JSON") from e
    license_data = body.get("license") if isinstance(body, dict) else None
    if not isinstance(license_data, str) or not license_data:
        raise ValueError("No license in response")
    return license_data


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


def _is_stale_replacement(stored_data: str, incoming: LicensePayload) -> bool:
    """True when the stored license was issued after the incoming one.

    Stores can overlap, so a slow response must not overwrite a newer license
    that landed while it was outstanding. An unreadable stored blob is not
    newer.
    """
    try:
        stored = verify_license_signature(stored_data)
    except ValueError:
        return False
    if stored.issued_at <= incoming.issued_at:
        return False
    logger.info(
        "Discarding license issued %s, already holding one issued %s",
        incoming.issued_at,
        stored.issued_at,
    )
    return True


def publish_license_cache(payload: LicensePayload, db_session: Session) -> None:
    """Publish metadata for a license already committed. Never raises.

    Drops the cached entry on failure rather than leaving a superseded one to
    serve out its TTL.
    """
    # Deferred import: ee.onyx.db.license imports this module.
    from ee.onyx.db.license import invalidate_license_cache, publish_license_metadata

    try:
        publish_license_metadata(payload, db_session)
    except Exception as cache_error:
        logger.warning("Failed to publish license cache: %s", cache_error)
        try:
            invalidate_license_cache()
        except Exception as invalidate_error:
            # The license is committed either way, and the enforcement
            # middleware re-reads the row before gating.
            logger.error(
                "License stored but its stale cache entry survives: %s",
                invalidate_error,
            )


def verify_and_store_license(
    db_session: Session,
    license_data: str,
    expected_tenant_id: str | None = None,
) -> LicensePayload:
    """Persist a license blob only after its signature verifies.

    Raises ValueError on an unverifiable blob, leaving the stored license
    untouched. A blob older than the one already stored is discarded.

    expected_tenant_id rejects a license addressed to someone else. The blob is
    signed but not addressed, so without it an upstream mix-up would replace
    this instance's credential with another tenant's.

    Returns the incoming payload even when it was discarded as older.
    """
    # Deferred import: ee.onyx.db.license imports this module.
    from ee.onyx.db.license import (
        acquire_license_store_lock,
        get_license,
        upsert_license,
    )

    payload = verify_license_signature(license_data)
    if expected_tenant_id is not None and payload.tenant_id != expected_tenant_id:
        raise ValueError("Control plane returned a license for a different tenant")

    acquire_license_store_lock(db_session)
    # The session may have loaded this row before the lock, and the identity
    # map would hand back those stale attributes. Expire so the read below is
    # the row as it stands now that writers are serialized.
    db_session.expire_all()
    stored = get_license(db_session)
    if stored and _is_stale_replacement(stored.license_data, payload):
        db_session.rollback()
        return payload
    if stored is None and expected_tenant_id is not None:
        # Reclaim renews an existing credential. A deleted row must stay gone.
        db_session.rollback()
        raise ValueError("Stored license was removed while the reclaim was in flight")
    upsert_license(db_session, license_data, commit=False)
    # Commit inside the lock, publish outside it: the Redis cache backend has
    # no socket timeout, so a stalled publish would hold the advisory lock and
    # wedge every other store, refresh, and delete behind it.
    db_session.commit()

    resume_license_reclaim()
    publish_license_cache(payload, db_session)
    return payload


class StoredLicense(NamedTuple):
    license_data: str
    payload: LicensePayload


def load_verified_license(db_session: Session) -> StoredLicense | None:
    """The stored license and its verified payload, or None when there is none.

    Raises ValueError on a stored blob that does not verify. Callers must
    decide whether that is terminal, since retrying cannot fix it.
    """
    # Deferred import: ee.onyx.db.license imports this module.
    from ee.onyx.db.license import get_license

    license_row = get_license(db_session)
    if not license_row or not license_row.license_data:
        return None
    return StoredLicense(
        license_row.license_data, verify_license_signature(license_row.license_data)
    )


def reclaim_license_from_control_plane(db_session: Session) -> LicensePayload | None:
    """Re-fetch this instance's license from the control plane, authenticating with the stored one.

    Returns None when there is no usable stored license to authenticate with,
    or when that license was already rejected. Raises ValueError when the
    control plane response has no valid license.

    Reads and sets the reclaim block itself, so callers must not
    re-implement it.
    """
    # Deferred import: ee.onyx.db.license imports this module.
    from ee.onyx.db.license import get_license

    stored = load_verified_license(db_session)
    if stored is None:
        return None

    # Addressed from the stored blob so a cache outage cannot stop a reclaim.
    stored_data, tenant_id = stored.license_data, stored.payload.tenant_id
    if not tenant_id or license_reclaim_is_blocked(stored_data):
        return None

    response = requests.get(
        f"{CLOUD_DATA_PLANE_URL}/proxy/license/{tenant_id}",
        headers={
            "Authorization": f"Bearer {stored_data}",
            "Content-Type": "application/json",
        },
        timeout=30,
    )
    if response.status_code in AUTH_REJECTED_STATUSES:
        # Only block while this blob is still the stored one, or a slow
        # rejection would suppress the replacement that overtook it.
        db_session.expire_all()
        current = get_license(db_session)
        if current and current.license_data == stored_data:
            block_license_reclaim(stored_data)
    response.raise_for_status()

    return verify_and_store_license(
        db_session,
        license_from_control_plane_response(response),
        expected_tenant_id=tenant_id,
    )


def license_fingerprint(license_data: str) -> str:
    """Short stable id for a license blob, safe to put in the cache."""
    return hashlib.sha256(license_data.encode()).hexdigest()[:32]


def block_license_reclaim(license_data: str) -> None:
    """Stop re-claiming the license that was just rejected. Never raises.

    Keyed to the rejected blob so a slow rejection cannot suppress a
    replacement that landed while it was in flight.
    """
    try:
        get_cache_backend().set(
            _LICENSE_RECLAIM_BLOCKED_KEY,
            license_fingerprint(license_data),
            ex=_LICENSE_RECLAIM_BLOCKED_TTL_SEC,
        )
    except Exception as e:
        logger.warning("Failed to set license reclaim block: %s", e)


def resume_license_reclaim() -> None:
    """Let re-claims run again immediately. Never raises."""
    try:
        get_cache_backend().delete(_LICENSE_RECLAIM_BLOCKED_KEY)
    except Exception as e:
        logger.warning("Failed to clear license reclaim block: %s", e)
    try:
        get_redis_client().delete(_LICENSE_RECLAIM_DEBOUNCE_KEY)
    except Exception as e:
        logger.warning("Failed to clear license reclaim debounce: %s", e)


def license_reclaim_is_blocked(license_data: str) -> bool:
    """True when this exact license was rejected as auth within the last day.

    A block naming a different blob is ignored, so installing a replacement
    resumes re-claims even if clearing the block failed. Fails open: an
    unreachable cache must not stop a legitimate reclaim.
    """
    try:
        blocked = get_cache_backend().get(_LICENSE_RECLAIM_BLOCKED_KEY)
    except Exception as e:
        logger.warning("Failed to read license reclaim block: %s", e)
        return False
    if blocked is None:
        return False
    return blocked.decode() == license_fingerprint(license_data)


def maybe_schedule_license_reclaim(expires_at: datetime, tenant_id: str) -> None:
    """Enqueue one license re-claim per debounce period when the stored license
    is inside LICENSE_RECLAIM_WINDOW. Never raises, since a scheduling failure
    must not affect the request that tripped it.
    """
    if not is_license_due_for_reclaim(expires_at):
        return
    # Both the debounce and the broker behind send_task are this Redis. Where
    # it does not exist the periodic poller owns reclaim instead.
    if CACHE_BACKEND != CacheBackendType.REDIS:
        return

    try:
        redis_client = get_redis_client()
        # SET NX doubles as the debounce and a cross-process lock: only the
        # first request in the window enqueues.
        if not redis_client.set(
            _LICENSE_RECLAIM_DEBOUNCE_KEY,
            "1",
            nx=True,
            ex=_LICENSE_RECLAIM_DEBOUNCE_TTL_SEC,
        ):
            return

        try:
            client_app.send_task(
                OnyxCeleryTask.RECLAIM_LICENSE,
                kwargs={"tenant_id": tenant_id},
                priority=OnyxCeleryPriority.HIGH,
                expires=_LICENSE_RECLAIM_DEBOUNCE_TTL_SEC,
            )
        except Exception:
            # The claim above is what stops other requests from enqueueing.
            # Holding it after a failed send would idle out the whole window.
            redis_client.delete(_LICENSE_RECLAIM_DEBOUNCE_KEY)
            raise
        logger.info("Scheduled license reclaim (license expires %s)", expires_at.date())
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
