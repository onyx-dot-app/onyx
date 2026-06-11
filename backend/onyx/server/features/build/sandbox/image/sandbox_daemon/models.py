"""Request/response models shared between the sandbox daemon and the api-server.

Both sides import these to keep the wire schema in sync. The daemon imports
them as ``sandbox_daemon.models`` (the Dockerfile copies ``sandbox_daemon/``
to ``/workspace/sandbox_daemon/``); the api-server imports the full module
path.
"""

from uuid import UUID

from pydantic import BaseModel
from pydantic import ConfigDict


class SnapshotCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID


# Restore has no response body — failures raise, success is the 204.
