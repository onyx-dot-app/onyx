"""Verify a source delivery and save sync intent in the same transaction."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from onyx.db.marketplace_sync import request_marketplace_sync__no_commit
from onyx.db.models import Marketplace
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.marketplace.provider import get_marketplace_adapter
from shared_configs.contextvars import get_current_tenant_id


def receive_marketplace_webhook__no_commit(
    marketplace_id: UUID,
    raw_body: bytes,
    *,
    signature: str,
    event: str,
    hook_id: str,
    db_session: Session,
) -> bool:
    """Return whether a matching push requested work; the caller owns commit."""
    query = select(Marketplace).where(Marketplace.id == marketplace_id)
    row = db_session.scalar(query.execution_options(populate_existing=True))
    if row is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND)
    get_marketplace_adapter(row, get_current_tenant_id()).verify_webhook(
        raw_body, signature=signature, event=event, hook_id=hook_id
    )
    # Reject unsigned callers before locking, then recheck the current source.
    row = db_session.scalar(
        query.with_for_update().execution_options(populate_existing=True)
    )
    if row is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND)
    result = get_marketplace_adapter(row, get_current_tenant_id()).verify_webhook(
        raw_body, signature=signature, event=event, hook_id=hook_id
    )
    if result != "ignored":
        row.webhook_last_delivery_at = db_session.scalar(select(func.clock_timestamp()))
    if result == "sync":
        request_marketplace_sync__no_commit(marketplace_id, db_session)
    return result == "sync"
