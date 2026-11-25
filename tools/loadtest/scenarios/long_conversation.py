"""Long multi-turn chat: grows one session's history to stress the
full-history load / token-counting / compression path that single-turn runs
never reach. Not in the default mix. See README.

Set ONYX_LONGCONV_USERS to keep that many long-lived users beside the other
selected scenarios, independent of -u weights. With a code mode profile
(ONYX_LONGCONV_MODEL=mock-profile-code-v1), history grows with program output
of observed size, so long sessions reach history compression.
"""

from __future__ import annotations

import os

from onyx_client.chat_user import OnyxChatUser
from onyx_client.env import env_int


class LongConversationUser(OnyxChatUser):
    abstract = False
    # >0 pins this many users; 0 weights them like other classes.
    fixed_count = env_int("ONYX_LONGCONV_USERS", 0)

    scenario_prefix: str = "longconv"
    mock_model: str | None = os.environ.get("ONYX_LONGCONV_MODEL")
    # Turns per session, at least 2 (a single turn defeats this scenario).
    max_session_turns: int = max(
        2, env_int("ONYX_LONGCONV_TURNS", env_int("ONYX_SESSION_TURNS", 20))
    )
