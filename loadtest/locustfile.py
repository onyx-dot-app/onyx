"""Locust entrypoint for Onyx chat load tests.

Usage (from this directory, after `uv sync`):

    ONYX_API_KEY=... uv run locust --headless -u 5 -r 1 -t 5m \
        -H https://<your-onyx-url>

Select scenarios by naming user classes; with none named, the default
weighted steady-state mix runs (BasicChatUser 70 / ChatWithSearchUser 20 /
MultiToolUser 8 / DeepResearchUser 2). Targeted reproducers are run on their
own, e.g.:

    ... uv run locust --headless -u 50 -r 5 -t 15m LongConversationUser
    ... uv run locust --headless -u 50 -r 5 -t 15m DisconnectUser

Set ONYX_SHAPE=stepramp to drive a staged ramp instead of a fixed user count
(see shapes.py). See README.md for all configuration env vars.
"""

import os

from onyx_client.chat_user import BasicChatUser
from scenarios import ChatWithSearchUser
from scenarios import DeepResearchUser
from scenarios import DisconnectUser
from scenarios import LongConversationUser
from scenarios import MultiToolUser

__all__ = [
    "BasicChatUser",
    "ChatWithSearchUser",
    "MultiToolUser",
    "DeepResearchUser",
    "LongConversationUser",
    "DisconnectUser",
]

# Only expose the ramp shape when explicitly requested: Locust auto-activates
# any LoadTestShape it discovers, which would otherwise override the manual
# -u/-r controls on every run.
if os.environ.get("ONYX_SHAPE") == "stepramp":
    from shapes import StepRampShape  # noqa: F401  (Locust discovers it via globals)

    __all__.append("StepRampShape")
