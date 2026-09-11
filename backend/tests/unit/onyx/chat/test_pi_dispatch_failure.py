"""Rejected preparation releases only its own chat admission fence."""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from onyx.chat.chat_processing_checker import (
    get_processing_run_id,
    set_processing_status,
)
from onyx.chat.pi import dispatch
from tests.unit.fakes import FakeCache


@pytest.mark.parametrize("stage", ["capture", "snapshot", "packets", "database"])
def test_rejected_preparation_releases_its_fence(
    monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    cache = FakeCache()
    session_id = uuid4()
    setup = MagicMock(chat_session_id=session_id, processing_run_id=41)
    setup.reserved_messages = [MagicMock(id=1)]
    set_processing_status(session_id, cache, True, run_id=41)
    capture = MagicMock(return_value=MagicMock())
    snapshot = MagicMock()
    packets = MagicMock()
    database = MagicMock()
    {
        "capture": capture,
        "snapshot": snapshot,
        "packets": packets,
        "database": database,
    }[stage].side_effect = ValueError("Rejected preparation")
    monkeypatch.setattr(dispatch.RunInputs, "capture", capture)
    monkeypatch.setattr(dispatch, "save_run_inputs", snapshot)
    monkeypatch.setattr(dispatch, "append_packet", packets)
    monkeypatch.setattr(dispatch, "create_runs", database)
    monkeypatch.setattr(dispatch, "any_runs_exist", lambda _: False)
    monkeypatch.setattr(dispatch, "get_cache_backend", lambda: cache)
    redis = MagicMock()
    monkeypatch.setattr(dispatch, "state_redis", lambda: redis)

    with pytest.raises(ValueError, match="Rejected preparation"):
        dispatch.prepare_dispatch(setup, uuid4(), [MagicMock()])
    assert get_processing_run_id(session_id, cache) is None
    redis.delete.assert_called_once()


def test_failed_preparation_cannot_clear_a_replacement_runs_fence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = FakeCache()
    session_id = uuid4()
    setup = MagicMock(chat_session_id=session_id, processing_run_id=41)
    setup.reserved_messages = [MagicMock(id=1)]
    set_processing_status(session_id, cache, True, run_id=41)

    def reject(*_: object) -> None:
        set_processing_status(session_id, cache, True, run_id=42)
        raise ValueError("Rejected preparation")

    monkeypatch.setattr(dispatch.RunInputs, "capture", reject)
    monkeypatch.setattr(dispatch, "get_cache_backend", lambda: cache)
    monkeypatch.setattr(dispatch, "state_redis", MagicMock())
    with pytest.raises(ValueError, match="Rejected preparation"):
        dispatch.prepare_dispatch(setup, uuid4(), [])
    assert get_processing_run_id(session_id, cache) == 42


@pytest.mark.parametrize("outcome", [True, ConnectionError("Database unavailable")])
def test_uncertain_commit_preserves_dispatch_state_for_reconciliation(
    monkeypatch: pytest.MonkeyPatch, outcome: bool | Exception
) -> None:
    cache = FakeCache()
    session_id = uuid4()
    setup = MagicMock(chat_session_id=session_id, processing_run_id=41)
    setup.reserved_messages = [MagicMock(id=1)]
    set_processing_status(session_id, cache, True, run_id=41)
    monkeypatch.setattr(dispatch.RunInputs, "capture", MagicMock())
    monkeypatch.setattr(dispatch, "save_run_inputs", MagicMock())
    monkeypatch.setattr(dispatch, "get_cache_backend", lambda: cache)
    monkeypatch.setattr(
        dispatch,
        "create_runs",
        MagicMock(side_effect=ConnectionError("Commit acknowledgement lost")),
    )
    existing = (
        MagicMock(side_effect=outcome)
        if isinstance(outcome, Exception)
        else MagicMock(return_value=outcome)
    )
    monkeypatch.setattr(dispatch, "any_runs_exist", existing)
    redis = MagicMock()
    monkeypatch.setattr(dispatch, "state_redis", lambda: redis)
    with pytest.raises(ConnectionError, match="Commit acknowledgement lost"):
        dispatch.prepare_dispatch(setup, uuid4(), [])
    assert get_processing_run_id(session_id, cache) == 41
    redis.delete.assert_not_called()
