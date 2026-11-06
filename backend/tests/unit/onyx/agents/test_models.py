import pytest
from pydantic import ValidationError

from onyx.agents.models import CompactionCheckpoint, RunStatus


@pytest.mark.parametrize("status", list(RunStatus))
def test_suspended_execution_is_not_terminal(status: RunStatus) -> None:
    assert status.is_terminal == (
        status not in (RunStatus.RUNNING, RunStatus.SUSPENDED)
    )


def test_compaction_checkpoint_requires_an_identified_history_boundary() -> None:
    with pytest.raises(ValidationError):
        CompactionCheckpoint(summary="Summary", covered_through_message_id="")
    checkpoint = CompactionCheckpoint(
        summary="Summary", covered_through_message_id="m1"
    )
    assert (
        CompactionCheckpoint.model_validate_json(checkpoint.model_dump_json())
        == checkpoint
    )
