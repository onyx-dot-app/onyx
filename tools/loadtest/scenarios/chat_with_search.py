"""Search turns with repeatable answer sizes and retrieval rounds.

The representative model drives real query expansion, embedding, retrieval,
classification, and document streaming. ONYX_SEARCH_MODEL selects explicit
stress or reliability profiles when needed.
"""

from __future__ import annotations

import os

from onyx_client.chat_user import OnyxChatUser


class ChatWithSearchUser(OnyxChatUser):
    abstract = False
    weight = 20

    scenario_prefix: str = "search"
    mock_model: str | None = os.environ.get(
        "ONYX_SEARCH_MODEL", "mock-profile-search-v1"
    )
