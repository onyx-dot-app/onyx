from uuid import UUID

from pydantic import BaseModel

from onyx.db.enums import ExternalAppType, IntegrationKind
from onyx.integrations.connection_models import IntegrationStatus
from onyx.integrations.models import ActionSettings, EffectivePolicy


class UploadResponse(BaseModel):
    """Response after successful file upload."""

    filename: str  # Sanitized filename
    path: str  # Relative path in sandbox (e.g., "attachments/doc.pdf")
    size_bytes: int  # File size in bytes


class BaseInstructionsResponse(BaseModel):
    content: str


class StaticPreviewGrant(BaseModel):
    tenant_id: str
    session_id: UUID
    user_id: UUID
    root: str
    files: dict[str, int]
    revisions: dict[str, str]


class StaticPreviewResponse(BaseModel):
    path: str
    expires_in: int


class TaskActionView(BaseModel):
    key: str
    display_name: str
    description: str | None
    # What a run does with Inherit.
    integration_policy: EffectivePolicy
    # A task Allow keeps the integration policy.
    locked: bool


class TaskIntegrationView(BaseModel):
    id: int
    name: str
    kind: IntegrationKind
    app_type: ExternalAppType | None
    status: IntegrationStatus
    actions: list[TaskActionView]
    # The task uses the integration.
    enabled: bool
    # The stored settings of the task for the integration; None when not
    # enabled.
    action_settings: ActionSettings | None
    # False: a run does not use the integration now (an admin turned it off,
    # or Craft cannot run it). The task keeps its settings.
    runnable: bool
