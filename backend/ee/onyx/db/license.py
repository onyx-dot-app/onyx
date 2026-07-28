"""Database and cache operations for the license table."""

import hashlib
import struct
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import NamedTuple

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ee.onyx.server.license.models import LicenseMetadata, LicensePayload
from onyx.auth.schemas import UserRole
from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheLock
from onyx.configs.constants import ANONYMOUS_USER_EMAIL
from onyx.db.enums import AccountType
from onyx.db.models import License, User
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

LICENSE_METADATA_KEY = "license:metadata"
LICENSE_CACHE_TTL_SECONDS = 86400  # 24 hours

# Serializes the row-read-compare-write in publish_license_metadata, and
# bounds acquisition: a contended lock publishes unserialized rather than
# stalling. The lease must comfortably outlive one SELECT plus two cache ops.
_LICENSE_CACHE_LOCK_KEY = "license:metadata:write"
_LICENSE_CACHE_LOCK_TIMEOUT_SEC = 30

# Namespaced + tenant-hashed so unrelated tenants don't block each other
# and the lock id can't collide with other advisory locks in the codebase.
_SEAT_LOCK_NAMESPACE = "onyx_seat_lock"
_LICENSE_STORE_LOCK_NAMESPACE = "onyx_license_store_lock"


def _advisory_lock_id(namespace: str, tenant_id: str) -> int:
    digest = hashlib.sha256(f"{namespace}:{tenant_id}".encode()).digest()
    # pg_advisory_xact_lock takes a signed 8-byte int.
    return struct.unpack("q", digest[:8])[0]


def seat_lock_id_for_tenant(tenant_id: str) -> int:
    return _advisory_lock_id(_SEAT_LOCK_NAMESPACE, tenant_id)


def acquire_license_store_lock(db_session: Session) -> None:
    """Serialize read-compare-write on the license row.

    Callers must read the stored blob and write its replacement inside this
    lock, or a slower response overwrites a newer license. Released on the
    caller's commit or rollback.
    """
    _acquire_advisory_lock(
        db_session,
        _advisory_lock_id(_LICENSE_STORE_LOCK_NAMESPACE, get_current_tenant_id()),
    )


def acquire_seat_lock(db_session: Session, tenant_id: str | None = None) -> None:
    """Tenant-scoped advisory lock; released on the caller's commit/rollback.

    Caller must run the seat check AND the seat-consuming write in the
    same transaction.
    """
    _acquire_advisory_lock(
        db_session, seat_lock_id_for_tenant(tenant_id or get_current_tenant_id())
    )


def _acquire_advisory_lock(db_session: Session, lock_id: int) -> None:
    # Bounded wait: a double-acquisition bug or wedged holder should fail
    # fast with lock_not_available, not hang until the idle-in-transaction
    # reaper kills the session (observed as 10-minute invite freezes).
    db_session.execute(text("SET LOCAL lock_timeout = '10s'"))
    db_session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_id)"),
        {"lock_id": lock_id},
    )
    # Restore the session default so the caller's later row-lock waits
    # aren't capped by the advisory-acquisition bound.
    db_session.execute(text("SET LOCAL lock_timeout = DEFAULT"))


class SeatAvailabilityResult(NamedTuple):
    """Result of a seat availability check."""

    available: bool
    error_message: str | None = None


# -----------------------------------------------------------------------------
# Database CRUD Operations
# -----------------------------------------------------------------------------


def get_license(db_session: Session) -> License | None:
    """
    Get the current license (singleton pattern - only one row).

    Args:
        db_session: Database session

    Returns:
        License object if exists, None otherwise
    """
    return db_session.execute(select(License)).scalars().first()


def upsert_license(
    db_session: Session, license_data: str, commit: bool = True
) -> License:
    """
    Insert or update the license (singleton pattern).

    commit=False flushes without committing, so the caller can keep the
    transaction, and its advisory locks, open across later work.

    Args:
        db_session: Database session
        license_data: Base64-encoded signed license blob

    Returns:
        The created or updated License object
    """
    license_row = get_license(db_session)

    if license_row:
        license_row.license_data = license_data
        logger.info("License updated")
    else:
        license_row = License(license_data=license_data)
        db_session.add(license_row)
        logger.info("License created")

    if commit:
        db_session.commit()
        db_session.refresh(license_row)
    else:
        db_session.flush()
    return license_row


def delete_license(db_session: Session) -> bool:
    """
    Delete the current license.

    Args:
        db_session: Database session

    Returns:
        True if deleted, False if no license existed
    """
    # Serialized with verify_and_store_license, so an in-flight reclaim that
    # started before the delete cannot re-insert the row afterward.
    acquire_license_store_lock(db_session)
    db_session.expire_all()
    existing = get_license(db_session)
    if existing:
        db_session.delete(existing)
        db_session.commit()
        # Under the cache lock: a store that committed just before this delete
        # publishes under the same lock and re-reads the row there, so its
        # entry either lands before this invalidate or is never written.
        try:
            with _license_cache_lock(None, wait=True):
                invalidate_license_cache()
        except Exception as e:
            logger.warning("License deleted but cache invalidation failed: %s", e)
        logger.info("License deleted")
        return True
    db_session.rollback()
    return False


# -----------------------------------------------------------------------------
# Seat Counting
# -----------------------------------------------------------------------------


def user_counts_toward_seats(user: User) -> bool:
    """Per-user predicate matching ``get_used_seats``'s SQL filter below.

    Self-hosted only — cloud counts ``UserTenantMapping`` rows instead.
    Keep in sync with ``get_used_seats``.
    """
    return (
        bool(user.is_active)
        and user.role != UserRole.EXT_PERM_USER
        and user.email != ANONYMOUS_USER_EMAIL
        and user.account_type != AccountType.SERVICE_ACCOUNT
    )


def get_used_seats(tenant_id: str | None = None) -> int:
    """
    Get current seat usage directly from database.

    Multi-tenant: counts active UserTenantMapping rows. Self-hosted:
    counts active users excluding SERVICE_ACCOUNT, EXT_PERM_USER, and
    the anonymous user. BOT is counted (real humans).

    Per-user predicate ``user_counts_toward_seats`` mirrors this filter.
    """
    if MULTI_TENANT:
        from ee.onyx.server.tenants.user_mapping import get_tenant_count

        return get_tenant_count(tenant_id or get_current_tenant_id())
    else:
        from onyx.db.engine.sql_engine import get_session_with_current_tenant

        with get_session_with_current_tenant() as db_session:
            result = db_session.execute(
                select(func.count())
                .select_from(User)
                .where(
                    User.is_active == True,  # noqa: E712  # ty: ignore[invalid-argument-type]
                    User.role != UserRole.EXT_PERM_USER,
                    User.email != ANONYMOUS_USER_EMAIL,  # ty: ignore[invalid-argument-type]
                    User.account_type != AccountType.SERVICE_ACCOUNT,
                )
            )
            return result.scalar() or 0


# -----------------------------------------------------------------------------
# Redis Cache Operations
# -----------------------------------------------------------------------------


def get_cached_license_metadata(tenant_id: str | None = None) -> LicenseMetadata | None:
    """
    Get license metadata from cache.

    Args:
        tenant_id: Tenant ID (for multi-tenant deployments)

    Returns:
        LicenseMetadata if cached, None otherwise
    """
    cache = get_cache_backend(tenant_id=tenant_id)
    cached = cache.get(LICENSE_METADATA_KEY)
    if not cached:
        return None

    try:
        cached_str = (
            cached.decode("utf-8") if isinstance(cached, bytes) else str(cached)
        )
        return LicenseMetadata.model_validate_json(cached_str)
    except Exception as e:
        logger.warning("Failed to parse cached license metadata: %s", e)
        return None


def invalidate_license_cache(tenant_id: str | None = None) -> None:
    """
    Invalidate the license metadata cache (not the license itself).

    Deletes the cached LicenseMetadata. The actual license in the database
    is not affected. Delete is idempotent — if the key doesn't exist, this
    is a no-op.

    Args:
        tenant_id: Tenant ID (for multi-tenant deployments)
    """
    cache = get_cache_backend(tenant_id=tenant_id)
    cache.delete(LICENSE_METADATA_KEY)
    logger.info("License cache invalidated")


def build_license_metadata(
    payload: LicensePayload,
    grace_period_end: datetime | None = None,
    tenant_id: str | None = None,
) -> tuple[LicenseMetadata, int]:
    """Metadata for *payload* plus the TTL that keeps its write-time status
    from outliving the boundary that would change it."""
    from ee.onyx.utils.license import get_license_status
    from ee.onyx.utils.license_expiry import (
        get_expiry_warning_stage,
        get_grace_period_end,
    )

    tenant = tenant_id or get_current_tenant_id()

    used_seats = get_used_seats(tenant)
    # Default the grace window to 14 days past expires_at so the license-
    # enforcement middleware returns GRACE_PERIOD (not GATED_ACCESS) during
    # that window — matching the banner copy and daily admin emails.
    effective_grace_end = grace_period_end or get_grace_period_end(payload.expires_at)
    # One clock sample for status and TTL, or a boundary crossing between the
    # two reads caches the old status for the full default TTL.
    now = datetime.now(timezone.utc)
    status = get_license_status(payload, effective_grace_end, now=now)
    warning_stage = get_expiry_warning_stage(payload.expires_at)

    metadata = LicenseMetadata(
        tenant_id=payload.tenant_id,
        organization_name=payload.organization_name,
        seats=payload.seats,
        used_seats=used_seats,
        plan_type=payload.plan_type,
        issued_at=payload.issued_at,
        expires_at=payload.expires_at,
        grace_period_end=effective_grace_end,
        status=status,
        expiry_warning_stage=warning_stage,
        source=payload.source,
        stripe_subscription_id=payload.stripe_subscription_id,
        customer_tier=payload.customer_tier,
    )

    ttl = LICENSE_CACHE_TTL_SECONDS
    for boundary in (payload.expires_at, effective_grace_end):
        if boundary > now:
            ttl = min(ttl, max(60, int((boundary - now).total_seconds()) + 1))
    return metadata, ttl


def update_license_cache(
    payload: LicensePayload,
    grace_period_end: datetime | None = None,
    tenant_id: str | None = None,
) -> LicenseMetadata:
    """Cache metadata for *payload*, expiring at its next status boundary.

    All statuses are cached (ACTIVE, GRACE_PERIOD, GATED_ACCESS): the frontend
    renders banners from them, and enforcement happens at the feature level.
    """
    metadata, ttl = build_license_metadata(payload, grace_period_end, tenant_id)
    cache = get_cache_backend(tenant_id=tenant_id)
    cache.set(
        LICENSE_METADATA_KEY,
        metadata.model_dump_json(),
        ex=ttl,
    )

    logger.info(
        "License cache updated: %s seats, status=%s",
        metadata.seats,
        metadata.status.value,
    )
    return metadata


def publish_license_metadata(
    db_session: Session,
    tenant_id: str | None = None,
    wait_for_lock: bool = True,
) -> LicenseMetadata | None:
    """Rebuild the cache from the license row, or None (uncached) without one.

    Writers commit under the store lock but publish after releasing it, so two
    of them can commit in one order and publish in the other. Deriving the
    entry from the row re-read under the cache write lock makes every publish
    converge on current row state: a slow publisher advertises its overtaker's
    license, and one that outlived a delete writes nothing.

    Raises ValueError when the stored blob does not verify.

    wait_for_lock=False is for callers that cannot afford to wait on a
    contended lock, and gives up serializing rather than the write itself.
    """
    # Deferred import: ee.onyx.utils.license imports this module.
    from ee.onyx.utils.license import verify_license_signature

    with _license_cache_lock(tenant_id, wait_for_lock) as lock:
        db_session.expire_all()
        license_row = get_license(db_session)
        if license_row is None:
            invalidate_license_cache(tenant_id)
            return None
        payload = verify_license_signature(license_row.license_data)
        cached = get_cached_license_metadata(tenant_id)
        if cached and cached.issued_at > payload.issued_at:
            return cached
        if lock is None:
            # An unserialized write can overwrite a newer entry or resurrect
            # one a delete just removed, so serve the caller without caching.
            metadata, _ = build_license_metadata(payload, tenant_id=tenant_id)
            return metadata
        metadata = update_license_cache(payload, tenant_id=tenant_id)
        if not lock.owned():
            # The lease expired mid-publish, so this write raced whatever
            # took the lock over. A dropped entry rebuilds on the next read.
            # A wrong one serves entitlements for its whole TTL.
            logger.warning("License cache lease lost mid-publish, dropping entry")
            invalidate_license_cache(tenant_id)
        return metadata


@contextmanager
def _license_cache_lock(
    tenant_id: str | None, wait: bool
) -> Generator[CacheLock | None]:
    """Serialize the guarded block, or run it unserialized if that is not possible.

    Serializing is an improvement on an unserialized write, never a
    precondition for one, and the Postgres backend holds this on a second
    connection. Failing to publish a committed license would read as
    unlicensed, so every way of not getting the lock still runs the block.
    """
    lock: CacheLock | None = None
    try:
        candidate = get_cache_backend(tenant_id=tenant_id).lock(
            _LICENSE_CACHE_LOCK_KEY, timeout=_LICENSE_CACHE_LOCK_TIMEOUT_SEC
        )
        if candidate.acquire(
            blocking=wait,
            blocking_timeout=_LICENSE_CACHE_LOCK_TIMEOUT_SEC if wait else None,
        ):
            lock = candidate
        else:
            logger.warning("License cache lock contended, publishing unserialized")
    except Exception as e:
        logger.warning("License cache lock errored (%s), publishing unserialized", e)

    try:
        yield lock
    finally:
        # Releasing a lease that already expired raises.
        if lock is not None and lock.owned():
            lock.release()


def refresh_license_cache(
    db_session: Session,
    tenant_id: str | None = None,
) -> LicenseMetadata | None:
    """
    Refresh the license cache from the database.

    Args:
        db_session: Database session
        tenant_id: Tenant ID (for multi-tenant deployments)

    Returns:
        LicenseMetadata if license exists, None otherwise
    """
    try:
        # Never waits: this must be callable from an event loop, and the
        # Postgres lock's acquisition poll sleeps.
        return publish_license_metadata(
            db_session, tenant_id=tenant_id, wait_for_lock=False
        )
    except ValueError as e:
        logger.error("Failed to verify license during cache refresh: %s", e)
        invalidate_license_cache(tenant_id)
        return None


def get_license_metadata(
    db_session: Session,
    tenant_id: str | None = None,
) -> LicenseMetadata | None:
    """
    Get license metadata, using cache if available.

    Args:
        db_session: Database session
        tenant_id: Tenant ID (for multi-tenant deployments)

    Returns:
        LicenseMetadata if license exists, None otherwise
    """
    # Try cache first
    cached = get_cached_license_metadata(tenant_id)
    if cached:
        return cached

    # Refresh from database
    return refresh_license_cache(db_session, tenant_id)


def check_seat_availability(
    db_session: Session,
    seats_needed: int = 1,
    tenant_id: str | None = None,
) -> SeatAvailabilityResult:
    """
    Check if there are enough seats available to add users.

    Args:
        db_session: Database session
        seats_needed: Number of seats needed (default 1)
        tenant_id: Tenant ID (for multi-tenant deployments)

    Returns:
        SeatAvailabilityResult with available=True if seats are available,
        or available=False with error_message if limit would be exceeded.
        Returns available=True if no license exists (self-hosted = unlimited).
    """
    metadata = get_license_metadata(db_session, tenant_id)

    # No license = no enforcement (self-hosted without license)
    if metadata is None:
        return SeatAvailabilityResult(available=True)

    # Calculate current usage directly from DB (not cache) for accuracy
    current_used = get_used_seats(tenant_id)
    total_seats = metadata.seats

    # Use > (not >=) to allow filling to exactly 100% capacity
    would_exceed_limit = current_used + seats_needed > total_seats
    if would_exceed_limit:
        return SeatAvailabilityResult(
            available=False,
            error_message=f"Seat limit would be exceeded: {current_used} of {total_seats} seats used, "
            f"cannot add {seats_needed} more user(s).",
        )

    return SeatAvailabilityResult(available=True)
