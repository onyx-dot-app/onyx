"""Persist signing intent before provider I/O; recheck authority before completion."""

import secrets
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.orm import Session

from onyx.db.marketplace_management import (
    assert_connected_marketplace_login,
    lock_managed_marketplace,
)
from onyx.db.models import Marketplace, User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.marketplace.models import MarketplaceManagementSnapshot


def prepare_marketplace_webhook__no_commit(
    marketplace_id: UUID,
    user: User,
    db_session: Session,
    *,
    expected: MarketplaceManagementSnapshot,
    full_ref: str,
) -> Marketplace:
    row = lock_managed_marketplace(
        marketplace_id, user, db_session, global_personal=True
    )
    if (
        row.provider != expected.provider
        or row.provider_config != expected.provider_config
        or row.login_user_id != expected.login_user_id
    ):
        raise OnyxError(
            OnyxErrorCode.CONFLICT, "Marketplace changed. Retry webhook setup."
        )
    assert_connected_marketplace_login(row.login_user_id, row.provider, db_session)
    if row.webhook_secret is None:
        db_session.execute(
            update(Marketplace)
            .where(Marketplace.id == row.id)
            .values(webhook_secret=secrets.token_urlsafe(32))
        )
        db_session.refresh(row, ["webhook_secret"])
    row.webhook_ref = full_ref
    db_session.flush()
    # A detached provider input cannot reopen a transaction after commit.
    return Marketplace(
        id=row.id,
        provider=row.provider,
        provider_config=row.provider_config,
        login_user_id=row.login_user_id,
        webhook_secret=row.webhook_secret,
        webhook_ref=row.webhook_ref,
        webhook_id=row.webhook_id,
    )


def finish_marketplace_webhook__no_commit(
    expected: Marketplace,
    hook_id: str,
    user: User,
    db_session: Session,
) -> None:
    row = lock_managed_marketplace(expected.id, user, db_session, global_personal=True)
    if (
        row.provider != expected.provider
        or row.provider_config != expected.provider_config
        or row.login_user_id != expected.login_user_id
        or row.webhook_ref != expected.webhook_ref
        or row.webhook_secret is None
        or expected.webhook_secret is None
        or row.webhook_secret.get_value(apply_mask=False)
        != expected.webhook_secret.get_value(apply_mask=False)
    ):
        raise OnyxError(
            OnyxErrorCode.CONFLICT, "Marketplace changed. Retry webhook setup."
        )
    assert_connected_marketplace_login(row.login_user_id, row.provider, db_session)
    row.webhook_id = hook_id
    db_session.flush()
