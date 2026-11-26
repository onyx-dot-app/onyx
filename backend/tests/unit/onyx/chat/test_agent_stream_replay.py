"""A resumed agent's live stream replays its claimed response as suspended."""

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from onyx.agents.models import RunStatus
from onyx.chat import agent_stream
from onyx.chat.agent_stream import BackgroundRunStream


@contextmanager
def _session(tenant_id: str) -> Iterator[MagicMock]:  # noqa: ARG001
    yield MagicMock()


def test_a_claimed_response_replays_with_its_unfinished_calls_open() -> None:
    response = SimpleNamespace(status=RunStatus.RUNNING)
    response.model_copy = lambda update: SimpleNamespace(**{**vars(response), **update})
    execution = SimpleNamespace(response=response, presentation={})
    presenter = MagicMock()
    # Only the fields that `_replay_saved` reads; no run or cache is needed.
    stream = object.__new__(BackgroundRunStream)
    stream._response_id = 7
    stream._root_session_id = uuid4()
    stream._presenter = presenter
    stream._lock = threading.Lock()
    stream._buffer = MagicMock()
    with (
        patch.object(agent_stream, "get_session_with_tenant", _session),
        patch.object(
            agent_stream,
            "read_suspended_response_replay",
            return_value=(execution, MagicMock()),
        ),
    ):
        stream._replay_saved("tenant")

    replayed = presenter.replay.call_args.args[0]
    assert replayed.status == RunStatus.SUSPENDED
