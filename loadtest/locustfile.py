"""Locust entrypoint for Onyx chat load tests.

Usage (from this directory, after `uv sync`):

    ONYX_API_KEY=... uv run locust --headless -u 5 -r 1 -t 5m \
        -H https://st-dev.onyx.app

Select scenarios with Locust's class picker, e.g.:

    ... uv run locust --headless -u 10 -r 2 -t 10m BasicChatUser ChatWithSearchUser

See README.md for configuration env vars and scenario details.
"""

from onyx_client.chat_user import BasicChatUser
from scenarios import ChatWithSearchUser
from scenarios import DeepResearchUser

__all__ = ["BasicChatUser", "ChatWithSearchUser", "DeepResearchUser"]
