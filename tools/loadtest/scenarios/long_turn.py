"""Long single turns: code mode turns of the observed long tail, with 20 or
more programs whose output is near the output limit
(mock-profile-code-v1-tail100). One turn holds a stream, the chat's growing
prompt, and program output for minutes. Not in the default mix. See README
"Long single turns".
"""

from __future__ import annotations

import os

from locust import constant
from onyx_client.chat_user import OnyxChatUser
from onyx_client.env import env_float


class LongTurnUser(OnyxChatUser):
    abstract = False

    scenario_prefix: str = "longturn"
    mock_model: str | None = os.environ.get(
        "ONYX_LONGTURN_MODEL", "mock-profile-code-v1-tail100"
    )
    wait_time = constant(env_float("ONYX_LONGTURN_WAIT_SECONDS", 15.0))
    stream_read_timeout: float = env_float("ONYX_LONGTURN_STREAM_READ_TIMEOUT", 600.0)
