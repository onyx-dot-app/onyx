"""Locust entrypoint for Onyx chat load tests.

With no user classes named, the default weighted mix runs (BasicChat 70 /
ChatWithSearch 20 / MultiTool 8 / DeepResearch 2); name a class to run a
targeted reproducer (LongConversationUser, DisconnectUser). For the worker /
threadpool concurrency sweep, name ThreadHogUser + HealthProbeUser (see
README "Worker concurrency sweep"). ONYX_SHAPE=stepramp drives a staged ramp.
See README.md for usage and env vars.
"""

import os

import prometheus_exporter  # noqa: F401  (registers the /metrics exporter)
from onyx_client.chat_user import BasicChatUser
from scenarios import ChatWithSearchUser
from scenarios import CompressionUser
from scenarios import DeepResearchUser
from scenarios import DisconnectUser
from scenarios import FileAttachmentUser
from scenarios import HealthProbeUser
from scenarios import LongConversationUser
from scenarios import MultiToolUser
from scenarios import ThreadHogUser

__all__ = [
    "BasicChatUser",
    "ChatWithSearchUser",
    "MultiToolUser",
    "DeepResearchUser",
    "LongConversationUser",
    "DisconnectUser",
    "CompressionUser",
    "FileAttachmentUser",
    "ThreadHogUser",
    "HealthProbeUser",
]

# Expose the ramp only on request: Locust auto-activates any shape it finds,
# which would override -u/-r on every run.
if os.environ.get("ONYX_SHAPE") == "stepramp":
    from shapes import StepRampShape  # noqa: F401  (Locust discovers it via globals)

    __all__.append("StepRampShape")
