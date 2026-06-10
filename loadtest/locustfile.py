"""Locust entrypoint for Onyx chat load tests.

Usage (from this directory, after `uv sync`):

    ONYX_API_KEY=... uv run locust --headless -u 5 -r 1 -t 5m \
        -H https://st-dev.onyx.app

See README.md for configuration env vars and scenario details.
"""

from onyx_client.chat_user import BasicChatUser

__all__ = ["BasicChatUser"]
