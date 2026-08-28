"""Chat turn that exercises the search tool path.

The `-tools1` model knob makes the mock LLM answer the first AUTO-tool-choice
cycle with an `internal_search` tool call, so Onyx genuinely executes the
search tool: query expansion, embedding model server, Vespa/OpenSearch
retrieval, document streaming. The follow-up LLM call (tool result in
history) streams the final answer.

The `<prefix>:first_search_doc` milestone measures time to the first
document batch — i.e. real retrieval-stack latency under load.
"""

from __future__ import annotations

import os

from onyx_client.chat_user import OnyxChatUser


class ChatWithSearchUser(OnyxChatUser):
    abstract = False
    weight = 20

    scenario_prefix: str = "search"
    mock_model: str | None = os.environ.get("ONYX_SEARCH_MODEL", "mock-tools1")
