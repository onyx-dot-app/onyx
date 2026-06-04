"""Request/response models shared between the sandbox daemon and the api-server.

Both sides import these to keep the wire schema in sync. The daemon imports
them as ``sandbox_daemon.models`` (the Dockerfile copies ``sandbox_daemon/``
to ``/workspace/sandbox_daemon/``); the api-server imports the full module
path.
"""

from typing import Annotated
from typing import Literal
from uuid import UUID

from pydantic import BaseModel
from pydantic import Field
from pydantic import model_validator

SnapshotCreateStatus = Literal["created", "empty"]

# Tenants are identified by alphanumeric / underscore / hyphen strings.
# UUIDs are validated by the UUID type; tenant_id is a free-form string from
# the api-server, so we constrain it here to prevent ``../`` traversal into
# the S3 key on snapshot upload.
TenantId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")]


class SnapshotCreateRequest(BaseModel):
    session_id: UUID
    tenant_id: TenantId
    s3_bucket: str
    snapshot_id: UUID


class SnapshotCreateResponse(BaseModel):
    status: SnapshotCreateStatus
    storage_path: str
    size_bytes: int


class SnapshotRestoreRequest(BaseModel):
    session_id: UUID
    tenant_id: TenantId
    s3_bucket: str
    storage_path: str

    @model_validator(mode="after")
    def _storage_path_under_tenant(self) -> "SnapshotRestoreRequest":
        """Reject any storage_path that doesn't sit under the tenant's
        snapshot prefix. Guards against a bug or compromise on the
        api-server side that mixes tenant IDs, and against ``..`` segments
        that would otherwise escape after a passing startswith check
        (e.g. ``t-1/snapshots/../../etc/passwd``).
        """
        expected_prefix = f"{self.tenant_id}/snapshots/"
        if not self.storage_path.startswith(expected_prefix):
            raise ValueError(f"storage_path must start with {expected_prefix!r}")
        if ".." in self.storage_path.split("/"):
            raise ValueError("storage_path must not contain '..' segments")
        return self


# Restore has no response body — failures raise, success is the 204.
