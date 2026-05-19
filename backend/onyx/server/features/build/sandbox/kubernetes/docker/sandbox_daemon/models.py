"""Request/response models shared between the sandbox_daemon daemon and the api-server.

Both sides import these to keep the wire schema in sync. The daemon imports
them as ``sandbox_daemon.models`` (the Dockerfile copies ``sandbox_daemon/`` to
``/workspace/sandbox_daemon/``); the api-server imports the full module path.
"""

from typing import Literal

from pydantic import BaseModel

SnapshotCreateStatus = Literal["created", "empty"]


class SnapshotCreateRequest(BaseModel):
    session_id: str
    tenant_id: str
    s3_bucket: str
    snapshot_id: str


class SnapshotCreateResponse(BaseModel):
    status: SnapshotCreateStatus
    storage_path: str
    size_bytes: int


class SnapshotRestoreRequest(BaseModel):
    session_id: str
    s3_bucket: str
    storage_path: str


# Restore has no response body — failures raise, success is the 200.
