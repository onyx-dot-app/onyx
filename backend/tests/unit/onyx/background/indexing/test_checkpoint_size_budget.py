"""check_checkpoint_size warns first, so an unbounded connector is visible
before its checkpoint reaches the hard limit and fails the index attempt.
"""

import logging

import pytest

from onyx.background.indexing import checkpointing_utils
from onyx.background.indexing.checkpointing_utils import check_checkpoint_size
from onyx.connectors.models import ConnectorCheckpoint


def test_checkpoint_over_warn_limit_warns(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(checkpointing_utils, "CHECKPOINT_SIZE_WARN_BYTES", 1)

    with caplog.at_level(logging.WARNING):
        check_checkpoint_size(ConnectorCheckpoint(has_more=True))

    assert "warn limit" in caplog.text


def test_checkpoint_over_hard_limit_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(checkpointing_utils, "CHECKPOINT_SIZE_LIMIT_BYTES", 1)

    with pytest.raises(ValueError, match="exceeds"):
        check_checkpoint_size(ConnectorCheckpoint(has_more=True))


def test_checkpoint_within_limits_is_silent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        check_checkpoint_size(ConnectorCheckpoint(has_more=True))

    assert caplog.text == ""
