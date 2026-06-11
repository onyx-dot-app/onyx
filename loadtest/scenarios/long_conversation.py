"""Long multi-turn chat: grows one session's history to stress the
full-history load / token-counting / compression path that single-turn runs
never reach. Run on its own (not in the default mix). See README.
"""

from __future__ import annotations

import os

from onyx_client.chat_user import _env_int
from onyx_client.chat_user import OnyxChatUser


class LongConversationUser(OnyxChatUser):
    abstract = False

    scenario_prefix: str = "longconv"
    mock_model: str | None = os.environ.get("ONYX_LONGCONV_MODEL")
    # Default 20 turns/session (base default is 1); honors ONYX_SESSION_TURNS.
    max_session_turns: int = max(2, _env_int("ONYX_SESSION_TURNS", 20))
