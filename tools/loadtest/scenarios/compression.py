"""Long-history chat that drives the summarization / compression path.

Builds on LongConversationUser: keeps one session alive for many turns and
sends large messages (default ONYX_MSG_CHARS), so the history quickly crosses
the model's input-token limit and Onyx summarizes/recompresses it every turn.
This is the path behind history-driven slowdowns and the compression
death-spiral incident (orphaned summaries → full recompression + giant
prompts each turn).

To trigger compression in a feasible number of turns, point it at a mock
model registered with a SMALL max_input_tokens (e.g. 16k) via
ONYX_LONGCONV_MODEL — otherwise the default 200k window needs a very long
history. See README "Compression / long-history".

Selected explicitly (not in the default mix):
    locust -f locustfile.py CompressionUser
"""

from __future__ import annotations

from onyx_client.env import env_int

from scenarios.long_conversation import LongConversationUser


class CompressionUser(LongConversationUser):
    abstract = False

    scenario_prefix: str = "compress"
    # Large messages by default so history grows fast (ONYX_MSG_CHARS overrides).
    default_msg_chars: int = 8000
    # Long sessions so the recompression path runs many times per session.
    max_session_turns: int = max(2, env_int("ONYX_SESSION_TURNS", 60))
