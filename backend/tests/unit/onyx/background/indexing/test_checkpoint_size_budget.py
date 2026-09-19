"""An oversized checkpoint must not kill the index attempt.

check_checkpoint_size used to raise ValueError, which failed the whole run for
a connector whose per-document dedup state grew past the budget. Warning
instead lets the connector shed that state and finish; the duplicates it then
re-yields are dropped later on doc_updated_at.
"""

import logging

import pytest

from onyx.background.indexing import checkpointing_utils
from onyx.background.indexing.checkpointing_utils import check_checkpoint_size
from onyx.connectors.models import ConnectorCheckpoint


def test_oversized_checkpoint_warns_instead_of_raising(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(checkpointing_utils, "CHECKPOINT_SIZE_BUDGET_BYTES", 1)

    with caplog.at_level(logging.WARNING):
        check_checkpoint_size(ConnectorCheckpoint(has_more=True))

    assert "exceeds" in caplog.text


def test_checkpoint_within_budget_is_silent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        check_checkpoint_size(ConnectorCheckpoint(has_more=True))

    assert caplog.text == ""
