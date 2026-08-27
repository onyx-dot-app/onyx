"""External-dependency-unit tests for proxy receipt recording.

Runs the recorder against Postgres and Redis: which actions leave receipts,
the PENDING to terminal transitions the hooks drive through
``finalize_recorded_flow``, the sweep, the owner-only listing, and the
announce stream the live SSE merge consumes.
"""

from __future__ import annotations

import json
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
    finalize_recorded_flow,
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
) -> list[tuple[UUID, str]]:
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
    entries = _record(db_session, session, _WRITE)
    force_receipt_created_at(
        db_session,
        entries[0][0],
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
    entries = _record(db_session, session, _WRITE)
    pop_receipt_announcement(session.id, timeout_s=1, cache=cache)

    finalize_recorded_flow(
        tenant_id=get_current_tenant_id(),
        session_id=session.id,
        entries=entries,
        transport_status=ReceiptStatus.CONFIRMED,
        response_body=None,
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
    entries = _record(db_session, session, _WRITE)
    pop_receipt_announcement(session.id, timeout_s=1, cache=cache)

    finalize_recorded_flow(
        tenant_id=get_current_tenant_id(),
        session_id=session.id,
        entries=entries,
        transport_status=ReceiptStatus.FAILED,
        response_body=None,
        cache_factory=lambda _tenant: cache,
    )
    # A late second verdict must not flip the recorded one.
    finalize_recorded_flow(
        tenant_id=get_current_tenant_id(),
        session_id=session.id,
        entries=entries,
        transport_status=ReceiptStatus.CONFIRMED,
        response_body=None,
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


def test_upload_flow_coalesces_into_one_receipt(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    test_user: User,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    session = build_session_with_user()
    cache = get_cache_backend()
    upload_action = MatchedAction(
        action_type="slack.files.write",
        display_name="Upload files",
        description="Upload a file.",
        policy=EndpointPolicy.ASK,
        effect=ActionEffect.WRITE,
    )
    matched = _matched(db_session, upload_action)

    # Step one: keyless record, then its response reveals file id and token.
    step_one_ids = record_pending_receipts(
        tenant_id=get_current_tenant_id(),
        session_id=session.id,
        matched_actions=matched,
        approval_id=None,
        cache_factory=lambda _tenant: cache,
    )
    step_one_body = json.dumps(
        {
            "ok": True,
            "file_id": "F42",
            "upload_url": "https://files.slack.com/upload/v1/tok42",
        }
    ).encode()
    finalize_recorded_flow(
        tenant_id=get_current_tenant_id(),
        session_id=session.id,
        entries=step_one_ids,
        transport_status=ReceiptStatus.CONFIRMED,
        response_body=step_one_body,
        cache_factory=lambda _tenant: cache,
    )

    # Step two: the raw-bytes POST carries only the token, resolved via the map.
    step_two_ids = record_pending_receipts(
        tenant_id=get_current_tenant_id(),
        session_id=session.id,
        matched_actions=matched,
        approval_id=None,
        cache_factory=lambda _tenant: cache,
        request_path="/upload/v1/tok42",
    )

    # Step three: completeUploadExternal names the file id in its request.
    step_three_ids = record_pending_receipts(
        tenant_id=get_current_tenant_id(),
        session_id=session.id,
        matched_actions=matched,
        approval_id=None,
        cache_factory=lambda _tenant: cache,
        request_body=json.dumps({"files": [{"id": "F42"}]}).encode(),
    )

    assert step_one_ids == step_two_ids == step_three_ids
    (row,) = get_session_receipts(db_session, session_id=session.id)
    assert row.operation_key == "slack.files.write:F42"
    assert row.status is ReceiptStatus.CONFIRMED

    # One receipt, two announcements: created and confirmed. The coalesced
    # later steps must not announce it again.
    first = pop_receipt_announcement(session.id, timeout_s=1, cache=cache)
    second = pop_receipt_announcement(session.id, timeout_s=1, cache=cache)
    assert first is not None and first.status is ReceiptStatus.PENDING
    assert second is not None and second.status is ReceiptStatus.CONFIRMED
    assert pop_receipt_announcement(session.id, timeout_s=1, cache=cache) is None


def test_upload_flow_failure_downgrades_the_coalesced_confirm(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    test_user: User,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    session = build_session_with_user()
    cache = get_cache_backend()
    upload_action = MatchedAction(
        action_type="slack.files.write",
        display_name="Upload files",
        description="Upload a file.",
        policy=EndpointPolicy.ASK,
        effect=ActionEffect.WRITE,
    )
    matched = _matched(db_session, upload_action)

    step_one = record_pending_receipts(
        tenant_id=get_current_tenant_id(),
        session_id=session.id,
        matched_actions=matched,
        approval_id=None,
        cache_factory=lambda _tenant: cache,
    )
    finalize_recorded_flow(
        tenant_id=get_current_tenant_id(),
        session_id=session.id,
        entries=step_one,
        transport_status=ReceiptStatus.CONFIRMED,
        response_body=json.dumps({"ok": True, "file_id": "F77"}).encode(),
        cache_factory=lambda _tenant: cache,
    )

    step_three = record_pending_receipts(
        tenant_id=get_current_tenant_id(),
        session_id=session.id,
        matched_actions=matched,
        approval_id=None,
        cache_factory=lambda _tenant: cache,
        request_body=json.dumps({"files": [{"id": "F77"}]}).encode(),
    )
    assert step_three == step_one
    # completeUploadExternal fails: the truer verdict overturns step one's
    # early CONFIRMED on the coalesced receipt.
    finalize_recorded_flow(
        tenant_id=get_current_tenant_id(),
        session_id=session.id,
        entries=step_three,
        transport_status=ReceiptStatus.CONFIRMED,
        response_body=json.dumps({"ok": False, "error": "not_in_channel"}).encode(),
        cache_factory=lambda _tenant: cache,
    )

    db_session.expire_all()
    (row,) = get_session_receipts(db_session, session_id=session.id)
    assert row.status is ReceiptStatus.FAILED


def test_refinement_persists_link_and_provider_verdict(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    test_user: User,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    session = build_session_with_user()
    cache = get_cache_backend()
    receipt_ids = _record(db_session, session, _WRITE)

    # Slack's 200 with ok=false must override the transport CONFIRMED.
    finalize_recorded_flow(
        tenant_id=get_current_tenant_id(),
        session_id=session.id,
        entries=receipt_ids,
        transport_status=ReceiptStatus.CONFIRMED,
        response_body=json.dumps({"ok": False, "error": "channel_not_found"}).encode(),
        cache_factory=lambda _tenant: cache,
    )
    db_session.expire_all()
    (row,) = get_session_receipts(db_session, session_id=session.id)
    assert row.status is ReceiptStatus.FAILED

    other_ids = _record(db_session, session, _WRITE)
    finalize_recorded_flow(
        tenant_id=get_current_tenant_id(),
        session_id=session.id,
        entries=other_ids,
        transport_status=ReceiptStatus.CONFIRMED,
        response_body=json.dumps({"ok": True, "channel": "C7", "ts": "1.2"}).encode(),
        cache_factory=lambda _tenant: cache,
    )
    db_session.expire_all()
    rows = {r.id: r for r in get_session_receipts(db_session, session_id=session.id)}
    assert rows[other_ids[0][0]].link == "https://slack.com/archives/C7/p12"
    assert rows[other_ids[0][0]].status is ReceiptStatus.CONFIRMED


def test_destination_refined_from_the_request(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    test_user: User,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    session = build_session_with_user()
    record_pending_receipts(
        tenant_id=get_current_tenant_id(),
        session_id=session.id,
        matched_actions=_matched(db_session, _WRITE),
        approval_id=None,
        cache_factory=lambda _tenant: get_cache_backend(),
        request_body=json.dumps({"channel": "exec-team", "text": "hi"}).encode(),
    )
    (row,) = get_session_receipts(db_session, session_id=session.id)
    assert row.destination == "#exec-team"
