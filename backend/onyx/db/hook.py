import datetime
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from sqlalchemy.orm import Session

from onyx.db.constants import UNSET
from onyx.db.constants import UnsetType
from onyx.db.enums import HookFailStrategy
from onyx.db.enums import HookPoint
from onyx.db.models import Hook
from onyx.db.models import HookExecutionLog
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError

# ── Hook CRUD ────────────────────────────────────────────────────────────


def get_hook_by_id(
    *,
    db_session: Session,
    hook_id: int,
    include_deleted: bool = False,
    include_creator: bool = False,
) -> Hook | None:
    stmt = select(Hook).where(Hook.id == hook_id)
    if not include_deleted:
        stmt = stmt.where(Hook.deleted.is_(False))
    if include_creator:
        stmt = stmt.options(selectinload(Hook.creator))
    return db_session.scalar(stmt)


def get_non_deleted_hook_by_hook_point(
    *,
    db_session: Session,
    hook_point: HookPoint,
    include_creator: bool = False,
) -> Hook | None:
    stmt = (
        select(Hook).where(Hook.hook_point == hook_point).where(Hook.deleted.is_(False))
    )
    if include_creator:
        stmt = stmt.options(selectinload(Hook.creator))
    return db_session.scalar(stmt)


def get_hooks(
    *,
    db_session: Session,
    include_deleted: bool = False,
    include_creator: bool = False,
) -> list[Hook]:
    stmt = select(Hook)
    if not include_deleted:
        stmt = stmt.where(Hook.deleted.is_(False))
    if include_creator:
        stmt = stmt.options(selectinload(Hook.creator))
    stmt = stmt.order_by(Hook.hook_point, Hook.created_at.desc())
    return list(db_session.scalars(stmt).all())


def create_hook__no_commit(
    *,
    db_session: Session,
    name: str,
    hook_point: HookPoint,
    endpoint_url: str | None = None,
    api_key: str | None = None,
    fail_strategy: HookFailStrategy,
    timeout_seconds: float,
    is_active: bool = False,
    is_reachable: bool | None = None,
    creator_id: UUID | None = None,
) -> Hook:
    """Create a new hook for the given hook point.

    At most one non-deleted hook per hook point is allowed. Raises
    OnyxError(CONFLICT) if a hook already exists, including under concurrent
    duplicate creates where the partial unique index fires an IntegrityError.
    """
    existing = get_non_deleted_hook_by_hook_point(
        db_session=db_session, hook_point=hook_point
    )
    if existing:
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            f"A hook for '{hook_point.value}' already exists (id={existing.id}).",
        )

    hook = Hook(
        name=name,
        hook_point=hook_point,
        endpoint_url=endpoint_url,
        api_key=api_key,
        fail_strategy=fail_strategy,
        timeout_seconds=timeout_seconds,
        is_active=is_active,
        is_reachable=is_reachable,
        creator_id=creator_id,
    )
    # Use a savepoint so that a failed insert only rolls back this operation,
    # not the entire outer transaction.
    savepoint = db_session.begin_nested()
    try:
        db_session.add(hook)
        savepoint.commit()
    except IntegrityError as exc:
        savepoint.rollback()
        if "ix_hook_one_non_deleted_per_point" in str(exc.orig):
            raise OnyxError(
                OnyxErrorCode.CONFLICT,
                f"A hook for '{hook_point.value}' already exists.",
            )
        raise  # re-raise unrelated integrity errors (FK violations, etc.)
    return hook


def update_hook__no_commit(
    *,
    db_session: Session,
    hook_id: int,
    name: str | None = None,
    endpoint_url: str | None | UnsetType = UNSET,
    api_key: str | None | UnsetType = UNSET,
    fail_strategy: HookFailStrategy | None = None,
    timeout_seconds: float | None = None,
    is_active: bool | None = None,
    is_reachable: bool | None = None,
    include_creator: bool = False,
) -> Hook:
    """Update hook fields.

    Sentinel conventions:
    - endpoint_url, api_key: pass UNSET to leave unchanged; pass None to clear.
    - name, fail_strategy, timeout_seconds, is_active, is_reachable: pass None to leave unchanged.
    """
    hook = get_hook_by_id(
        db_session=db_session, hook_id=hook_id, include_creator=include_creator
    )
    if hook is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, f"Hook with id {hook_id} not found.")

    if name is not None:
        hook.name = name
    if not isinstance(endpoint_url, UnsetType):
        hook.endpoint_url = endpoint_url
    if not isinstance(api_key, UnsetType):
        hook.api_key = api_key  # EncryptedString coerces str → SensitiveValue at the ORM level  # ty: ignore[invalid-assignment]
    if fail_strategy is not None:
        hook.fail_strategy = fail_strategy
    if timeout_seconds is not None:
        hook.timeout_seconds = timeout_seconds
    if is_active is not None:
        hook.is_active = is_active
    if is_reachable is not None:
        hook.is_reachable = is_reachable

    db_session.flush()
    return hook


def delete_hook__no_commit(
    *,
    db_session: Session,
    hook_id: int,
) -> None:
    hook = get_hook_by_id(db_session=db_session, hook_id=hook_id)
    if hook is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, f"Hook with id {hook_id} not found.")

    hook.deleted = True
    hook.is_active = False
    db_session.flush()


# ── HookExecutionLog CRUD ────────────────────────────────────────────────


def create_hook_execution_log__no_commit(
    *,
    db_session: Session,
    hook_id: int,
    is_success: bool,
    error_message: str | None = None,
    status_code: int | None = None,
    duration_ms: int | None = None,
) -> HookExecutionLog:
    log = HookExecutionLog(
        hook_id=hook_id,
        is_success=is_success,
        error_message=error_message,
        status_code=status_code,
        duration_ms=duration_ms,
    )
    db_session.add(log)
    db_session.flush()
    return log


def get_hook_execution_logs(
    *,
    db_session: Session,
    hook_id: int,
    limit: int,
) -> list[HookExecutionLog]:
    stmt = (
        select(HookExecutionLog)
        .where(HookExecutionLog.hook_id == hook_id)
        .order_by(HookExecutionLog.created_at.desc())
        .limit(limit)
    )
    return list(db_session.scalars(stmt).all())


def cleanup_old_execution_logs__no_commit(
    *,
    db_session: Session,
    max_age_days: int,
) -> int:
    """Delete execution logs older than max_age_days. Returns the number of rows deleted."""
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        days=max_age_days
    )
    result: CursorResult = db_session.execute(  # ty: ignore[invalid-assignment]
        delete(HookExecutionLog)
        .where(HookExecutionLog.created_at < cutoff)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount
