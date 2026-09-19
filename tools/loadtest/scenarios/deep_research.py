"""Deep research turn.

No special model knobs are needed: the DR orchestrator and research agents
call the LLM with tool_choice=REQUIRED, and the mock's branching handles the
whole sequence statelessly — clarification (`generate_plan`), plan text,
research_agent spawn (parallelism via the `-agents<N>` knob), per-agent
search → intermediate report, then the final report.

This is the heaviest scenario: one turn holds the streaming connection (and
api-server resources) across ~8+ LLM calls plus real search-tool executions.
"""

from __future__ import annotations

import os

from locust import constant
from onyx_client.chat_user import OnyxChatUser
from onyx_client.env import env_float


class DeepResearchUser(OnyxChatUser):
    abstract = False
    weight = 2

    scenario_prefix: str = "dr"
    deep_research: bool = True
    mock_model: str | None = os.environ.get("ONYX_DR_MODEL", "mock-agents2")

    # DR turns run minutes, not seconds: think longer between turns and
    # tolerate longer inter-chunk silence (heartbeats should still arrive).
    wait_time = constant(env_float("ONYX_DR_WAIT_SECONDS", 30.0))
    stream_read_timeout: float = env_float("ONYX_DR_STREAM_READ_TIMEOUT", 300.0)
