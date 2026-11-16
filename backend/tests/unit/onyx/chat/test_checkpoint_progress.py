"""Saved run progress decodes after the server that saved it is replaced."""

from onyx.agents.models import RunProgress
from onyx.chat.checkpoint import CHECKPOINT_PAYLOAD_TYPES, CheckpointSerializer


def test_progress_with_a_tool_configuration_digest_decodes() -> None:
    serializer = CheckpointSerializer(CHECKPOINT_PAYLOAD_TYPES)
    saved = serializer.encode_progress(RunProgress(step_index=1, step_limit=3)) | {
        "tool_configuration_digest": "digest"
    }

    assert serializer.decode_progress(saved) == RunProgress(step_index=1, step_limit=3)
