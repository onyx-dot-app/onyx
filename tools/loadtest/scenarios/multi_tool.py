"""Chat turn that calls several retrieval tools in parallel (the `-tools3`
knob), exercising concurrent tool execution within one turn. Degrades to a
single search if the persona offers fewer tools. Part of the default mix.
"""

from __future__ import annotations

import os

from onyx_client.chat_user import OnyxChatUser


class MultiToolUser(OnyxChatUser):
    abstract = False
    weight = 8

    scenario_prefix: str = "multitool"
    mock_model: str | None = os.environ.get("ONYX_MULTITOOL_MODEL", "mock-tools3")
