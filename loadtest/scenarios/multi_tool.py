"""Chat turn that drives multiple retrieval tools in parallel.

The `-tools3` knob makes the mock LLM answer the first AUTO-tool-choice cycle
with parallel calls to every retrieval tool the persona offers (internal
search, web search, open url), so Onyx executes them concurrently inside one
chat turn — fan-out over the embedding model server, Vespa/OpenSearch, and the
web fetch path, then a single follow-up answer call.

A small but real slice of production traffic; weighted accordingly in the
default mix. Degrades gracefully to a single search when the persona exposes
only one retrieval tool.
"""

from __future__ import annotations

import os

from onyx_client.chat_user import OnyxChatUser


class MultiToolUser(OnyxChatUser):
    abstract = False
    weight = 8

    scenario_prefix: str = "multitool"
    mock_model: str | None = os.environ.get("ONYX_MULTITOOL_MODEL", "mock-tools3")
