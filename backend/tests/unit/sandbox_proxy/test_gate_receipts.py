"""Unit tests for the gate's receipt wiring.

The recorder itself is covered against Postgres elsewhere; here the risk is
the mitmproxy plumbing: the metadata carrier surviving flow copies, the
response and error hooks mapping transport outcomes to verdicts, and record
failures never blocking the request. The recorder functions are patched with
capturing fakes so no service is touched.
"""

from __future__ import annotations

import asyncio
import copy
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from mitmproxy.test import tflow

from onyx.db.enums import ActionEffect, EndpointPolicy, GatedAppKind, ReceiptStatus
from onyx.external_apps.matching.engine import (
    AllMatchedActions,
    GatedTarget,
    MatchedAction,
)
from onyx.sandbox_proxy.addons import gate as gate_module
from onyx.sandbox_proxy.addons.gate import (
    RECEIPT_FLOW_KEY,
    GateAddon,
    _IdentityResolver,
)
from onyx.sandbox_proxy.credential_injection import CredentialInjectionDispatcher
from onyx.sandbox_proxy.identity import SessionContext
from onyx.sandbox_proxy.request_evaluator import RequestEvaluator

_MATCHED = AllMatchedActions(
    actions=(
        MatchedAction(
            action_type="slack.messages.write",
            display_name="Post a message",
            description="Post a message.",
            policy=EndpointPolicy.ASK,
            effect=ActionEffect.WRITE,
        ),
    ),
    target=GatedTarget(kind=GatedAppKind.EXTERNAL_APP, id=1, app_name="Slack"),
)


def _unused_factory(_tenant_id: str) -> Any:
    raise AssertionError("cache factory must not be consulted, recorder is patched")


def _addon() -> GateAddon:
    return GateAddon(
        # The hooks under test never resolve identities or evaluate requests.
        identity=cast("_IdentityResolver", None),
        request_evaluator=cast("RequestEvaluator", None),
        cache_factory=_unused_factory,
        proxy_instance_id="proxy-test",
        credential_dispatcher=CredentialInjectionDispatcher([]),
    )


def _ctx() -> SessionContext:
    return SessionContext(
        session_id=uuid4(),
        user_id=uuid4(),
        sandbox_id=uuid4(),
        tenant_id="public",
        sandbox_name="sandbox-test",
        sandbox_ip="10.0.0.1",
    )


def test_record_stashes_a_serializable_carrier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt_id = uuid4()
    calls: list[dict[str, Any]] = []

    def _fake_record(**kwargs: Any) -> list[UUID]:
        calls.append(kwargs)
        return [receipt_id]

    monkeypatch.setattr(gate_module, "record_pending_receipts", _fake_record)
    addon = _addon()
    flow = tflow.tflow()
    ctx = _ctx()

    asyncio.run(addon._record_receipts(flow, ctx, _MATCHED, approval_id=None))

    carrier = flow.metadata[RECEIPT_FLOW_KEY]
    assert carrier == {
        "tenant_id": "public",
        "session_id": str(ctx.session_id),
        "receipt_ids": [str(receipt_id)],
    }
    # mitmproxy deep-copies and serializes metadata, so primitives only.
    assert copy.deepcopy(carrier) == carrier
    assert calls[0]["approval_id"] is None


def test_record_failure_never_blocks_the_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(**_kwargs: Any) -> list[UUID]:
        raise RuntimeError("db down")

    monkeypatch.setattr(gate_module, "record_pending_receipts", _boom)
    addon = _addon()
    flow = tflow.tflow()

    asyncio.run(addon._record_receipts(flow, _ctx(), _MATCHED, approval_id=None))

    assert RECEIPT_FLOW_KEY not in flow.metadata
    assert flow.response is None


def _finalize_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def _fake_finalize(**kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(gate_module, "finalize_receipts", _fake_finalize)
    return calls


def _recorded_flow(status_code: int | None) -> Any:
    flow = tflow.tflow(resp=status_code is not None)
    if status_code is not None:
        assert flow.response is not None
        flow.response.status_code = status_code
    flow.metadata[RECEIPT_FLOW_KEY] = {
        "tenant_id": "public",
        "session_id": str(uuid4()),
        "receipt_ids": [str(uuid4())],
    }
    return flow


@pytest.mark.parametrize(
    "status_code,expected",
    [
        (200, ReceiptStatus.CONFIRMED),
        (302, ReceiptStatus.CONFIRMED),
        (403, ReceiptStatus.FAILED),
        (500, ReceiptStatus.FAILED),
    ],
)
def test_response_hook_maps_status_to_verdict(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    expected: ReceiptStatus,
) -> None:
    calls = _finalize_capture(monkeypatch)
    addon = _addon()
    flow = _recorded_flow(status_code)

    asyncio.run(addon.response(flow))

    assert calls[0]["status"] is expected
    # The carrier is consumed, a later hook cannot double-finalize.
    assert RECEIPT_FLOW_KEY not in flow.metadata
    asyncio.run(addon.response(flow))
    assert len(calls) == 1


def test_error_after_ok_headers_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _finalize_capture(monkeypatch)
    addon = _addon()

    # Headers said 200, the body never finished: the origin may have
    # committed, so the verdict is UNKNOWN.
    asyncio.run(addon.error(_recorded_flow(200)))
    assert calls[0]["status"] is ReceiptStatus.UNKNOWN

    # No response at all: the request never got a verdict, FAILED.
    asyncio.run(addon.error(_recorded_flow(None)))
    assert calls[1]["status"] is ReceiptStatus.FAILED


def test_hooks_ignore_unrecorded_flows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _finalize_capture(monkeypatch)
    addon = _addon()

    asyncio.run(addon.response(tflow.tflow(resp=True)))
    asyncio.run(addon.error(tflow.tflow()))

    assert calls == []


def test_always_policy_writes_still_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    addon = _addon()
    recorded: list[Any] = []

    async def _fake_record(*args: Any, **kwargs: Any) -> None:
        recorded.append((args, kwargs))

    session_id = uuid4()
    monkeypatch.setattr(addon, "_record_receipts", _fake_record)
    monkeypatch.setattr(
        addon, "_resolve_gated_session", lambda _flow, _sandbox: session_id
    )
    flow = tflow.tflow()
    sandbox = _ctx().without_session()

    asyncio.run(addon._record_always_write_receipts(flow, sandbox, _MATCHED))

    assert len(recorded) == 1
    ctx = recorded[0][0][1]
    assert ctx.session_id == session_id


def test_always_policy_reads_skip_session_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    addon = _addon()

    def _must_not_resolve(_flow: Any, _sandbox: Any) -> None:
        raise AssertionError("reads must not pay session resolution")

    monkeypatch.setattr(addon, "_resolve_gated_session", _must_not_resolve)
    read_only = AllMatchedActions(
        actions=(
            MatchedAction(
                action_type="slack.messages.read",
                display_name="Read messages",
                description="Read messages.",
                policy=EndpointPolicy.ALWAYS,
                effect=ActionEffect.READ,
            ),
        ),
        target=GatedTarget(kind=GatedAppKind.EXTERNAL_APP, id=1, app_name="Slack"),
    )

    asyncio.run(
        addon._record_always_write_receipts(
            tflow.tflow(), _ctx().without_session(), read_only
        )
    )


def test_always_policy_unattributable_write_goes_unrecorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    addon = _addon()

    async def _must_not_record(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("unattributable writes record nothing")

    monkeypatch.setattr(addon, "_record_receipts", _must_not_record)
    monkeypatch.setattr(addon, "_resolve_gated_session", lambda _flow, _sandbox: None)

    asyncio.run(
        addon._record_always_write_receipts(
            tflow.tflow(), _ctx().without_session(), _MATCHED
        )
    )
