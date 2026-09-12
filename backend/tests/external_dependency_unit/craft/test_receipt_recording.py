"""External-dependency-unit tests for proxy receipt recording.

Runs the recorder against Postgres and Redis: which actions leave receipts,
the PENDING to terminal transitions the hooks drive through
``finalize_receipts``, the sweep, the owner-only listing, and the announce
stream the live SSE merge consumes.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from onyx.cache.factory import get_cache_backend
from onyx.db.enums import (
    ActionEffect,
    EndpointPolicy,
    GatedAppKind,
    ReceiptStatus,
)
from onyx.db.models import BuildSession, User
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.matching.engine import (
    AllMatchedActions,
    GatedTarget,
    MatchedAction,
)
from onyx.sandbox_proxy.receipt_recorder import (
    finalize_receipts,
    pop_receipt_announcement,
    receipt_worthy_actions,
    record_pending_receipts,
)
from onyx.server.features.build.db.action_approval import insert_action_approval
from onyx.server.features.build.db.receipt import get_session_receipts
from onyx.server.features.build.session.api import list_receipts
from shared_configs.contextvars import get_current_tenant_id
from tests.external_dependency_unit.craft.db_helpers import (
    force_receipt_created_at,
    make_external_app,
    make_skill,
    make_user,
)

_WRITE = MatchedAction(
    action_type="slack.messages.write",
    display_name="Post a message",
    description="Post a message.",
    policy=EndpointPolicy.ASK,
    effect=ActionEffect.WRITE,
)
_READ = MatchedAction(
    action_type="slack.messages.read",
    display_name="Read messages",
    description="Read messages.",
    policy=EndpointPolicy.ALWAYS,
    effect=ActionEffect.READ,
)


def _matched(db_session: Session, *actions: MatchedAction) -> AllMatchedActions:
    skill = make_skill(db_session)
    app = make_external_app(db_session, skill=skill, auth_template={"kind": "none"})
    db_session.commit()
    return AllMatchedActions(
        actions=tuple(actions),
        target=GatedTarget(kind=GatedAppKind.EXTERNAL_APP, id=app.id, app_name="Slack"),
    )


def _record(
    db_session: Session,
    session: BuildSession,
    *actions: MatchedAction,
    approval_id: UUID | None = None,
) -> list[UUID]:
    return record_pending_receipts(
        tenant_id=get_current_tenant_id(),
        session_id=session.id,
        matched_actions=_matched(db_session, *actions),
        approval_id=approval_id,
        cache_factory=lambda _tenant: get_cache_backend(),
    )


def test_write_actions_leave_pending_receipts(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    test_user: User,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    session = build_session_with_user()

    receipt_ids = _record(db_session, session, _WRITE, _READ)

    assert len(receipt_ids) == 1
    (row,) = get_session_receipts(db_session, session_id=session.id)
    assert row.action_type == "slack.messages.write"
    assert row.effect == "write"
    assert row.destination == "Slack"
    assert row.status is ReceiptStatus.PENDING
    assert row.gated_app_id is not None

    packet = pop_receipt_announcement(
        session.id, timeout_s=1, cache=get_cache_backend()
    )
    assert packet is not None
    assert packet.status is ReceiptStatus.PENDING
    assert (
        pop_receipt_announcement(session.id, timeout_s=1, cache=get_cache_backend())
        is None
    )


def test_auto_passing_reads_leave_nothing(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    test_user: User,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    session = build_session_with_user()

    assert _record(db_session, session, _READ) == []
    assert get_session_receipts(db_session, session_id=session.id) == []


def test_approved_read_stays_visible(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    test_user: User,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    session = build_session_with_user()
    approval = insert_action_approval(
        db_session,
        session_id=session.id,
        actions=[_READ.model_dump(mode="json")],
        app_name="Slack",
        payload={},
    )

    receipt_ids = _record(db_session, session, _READ, approval_id=approval.approval_id)

    assert len(receipt_ids) == 1
    (row,) = get_session_receipts(db_session, session_id=session.id)
    assert row.effect == "read"
    assert row.approval_id == approval.approval_id
    assert receipt_worthy_actions(_matched(db_session, _READ), approval_id=None) == []


def test_listing_is_owner_only_and_sweeps(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    test_user: User,
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    session = build_session_with_user()
    receipt_ids = _record(db_session, session, _WRITE)
    force_receipt_created_at(
        db_session,
        receipt_ids[0],
        datetime.now(timezone.utc) - timedelta(hours=1),
    )

    listed = list_receipts(session.id, user=test_user, db_session=db_session)
    assert [r.status for r in listed] == [ReceiptStatus.UNKNOWN]

    other = make_user(db_session, standard_account=True)
    db_session.commit()
    with pytest.raises(OnyxError):
        list_receipts(session.id, user=other, db_session=db_session)


def test_finalize_confirms(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    test_user: User,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    session = build_session_with_user()
    cache = get_cache_backend()
    receipt_ids = _record(db_session, session, _WRITE)
    pop_receipt_announcement(session.id, timeout_s=1, cache=cache)

    finalize_receipts(
        tenant_id=get_current_tenant_id(),
        session_id=session.id,
        receipt_ids=receipt_ids,
        status=ReceiptStatus.CONFIRMED,
        cache_factory=lambda _tenant: cache,
    )

    db_session.expire_all()
    (row,) = get_session_receipts(db_session, session_id=session.id)
    assert row.status is ReceiptStatus.CONFIRMED
    packet = pop_receipt_announcement(session.id, timeout_s=1, cache=cache)
    assert packet is not None and packet.status is ReceiptStatus.CONFIRMED


def test_finalize_failed_verdicts_do_not_flip(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    test_user: User,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    session = build_session_with_user()
    cache = get_cache_backend()
    receipt_ids = _record(db_session, session, _WRITE)
    pop_receipt_announcement(session.id, timeout_s=1, cache=cache)

    finalize_receipts(
        tenant_id=get_current_tenant_id(),
        session_id=session.id,
        receipt_ids=receipt_ids,
        status=ReceiptStatus.FAILED,
        cache_factory=lambda _tenant: cache,
    )
    # A late second verdict must not flip the recorded one.
    finalize_receipts(
        tenant_id=get_current_tenant_id(),
        session_id=session.id,
        receipt_ids=receipt_ids,
        status=ReceiptStatus.CONFIRMED,
        cache_factory=lambda _tenant: cache,
    )

    db_session.expire_all()
    (row,) = get_session_receipts(db_session, session_id=session.id)
    assert row.status is ReceiptStatus.FAILED
    packet = pop_receipt_announcement(session.id, timeout_s=1, cache=cache)
    assert packet is not None and packet.status is ReceiptStatus.FAILED
    assert pop_receipt_announcement(session.id, timeout_s=1, cache=cache) is None


def test_multiple_writes_each_get_a_receipt(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    test_user: User,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    session = build_session_with_user()
    other_write = MatchedAction(
        action_type="slack.files.write",
        display_name="Upload files",
        description="Upload a file.",
        policy=EndpointPolicy.ASK,
        effect=ActionEffect.WRITE,
    )

    receipt_ids = _record(db_session, session, _WRITE, other_write, _READ)

    assert len(receipt_ids) == 2
    rows = get_session_receipts(db_session, session_id=session.id)
    assert {row.action_type for row in rows} == {
        "slack.messages.write",
        "slack.files.write",
    }
