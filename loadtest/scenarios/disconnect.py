"""Chat turns where the client disconnects mid-stream.

Each turn starts a normal streaming chat, then drops the connection the moment
the configured milestone arrives (default: the first answer token) — a user
closing the tab while the answer is still streaming. The server is left
holding a turn that no one is reading, which exercises disconnect detection
and the cleanup of whatever that turn was holding (DB transactions/connections,
per-stream buffers). Resource that isn't released on client disconnect is a
classic slow leak under load.

Turns are recorded as `<prefix>:disconnected` (plus whatever milestones were
reached first), kept separate from success/failure so the disconnect rate is
explicit rather than masquerading as errors.

Tuning (env):
    ONYX_DISCONNECT_AFTER   milestone to disconnect after — one of
                            first_packet, first_search_doc, first_answer_token
                            (default), first_dr_plan, first_research_agent.

Selected explicitly (not part of the default steady-state mix), e.g.:
    locust -f locustfile.py DisconnectUser
"""

from __future__ import annotations

import os

from onyx_client.chat_user import OnyxChatUser


class DisconnectUser(OnyxChatUser):
    abstract = False

    scenario_prefix: str = "disconnect"
    disconnect_after_milestone: str | None = os.environ.get(
        "ONYX_DISCONNECT_AFTER", "first_answer_token"
    )
