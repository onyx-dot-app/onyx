"""Multi-turn conversation that grows a long chat history.

Each user keeps one chat session alive for ONYX_SESSION_TURNS turns, chaining
parent_message_id off the previous assistant reply so the message history
grows every turn. This exercises the path real long-running chats hit:
loading the full thread, history token-counting, and (past the model's input
window) summarization/compression on every turn — the ingredient missing from
the single-turn scenarios, and the one behind history-driven slowdowns and
compression blowups.

Tuning (env):
    ONYX_SESSION_TURNS   turns per session before starting a fresh one (>1;
                         this scenario forces a sane minimum if unset).
    ONYX_LONGCONV_MODEL  mock model knob (default plain chat, no tools).

Selected explicitly (not part of the default steady-state mix), e.g.:
    locust -f locustfile.py LongConversationUser
"""

from __future__ import annotations

import os

from onyx_client.chat_user import _env_int
from onyx_client.chat_user import OnyxChatUser


class LongConversationUser(OnyxChatUser):
    abstract = False

    scenario_prefix: str = "longconv"
    mock_model: str | None = os.environ.get("ONYX_LONGCONV_MODEL")

    # Keep a session alive for many turns so history actually grows long.
    # Defaults to 20 here (vs the base default of 1) but still honors an
    # explicit ONYX_SESSION_TURNS override.
    max_session_turns: int = max(2, _env_int("ONYX_SESSION_TURNS", 20))
