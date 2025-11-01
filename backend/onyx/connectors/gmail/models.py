from pydantic import Field

from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorCheckpoint


class GmailCheckpoint(ConnectorCheckpoint):
    user_emails: list[str] | None = None
    remaining_user_emails: list[str] = Field(default_factory=list)
    current_user_email: str | None = None
    next_page_token: str | None = None
    pending_thread_ids: list[str] = Field(default_factory=list)
    window_start: SecondsSinceUnixEpoch | None = None
    window_end: SecondsSinceUnixEpoch | None = None
