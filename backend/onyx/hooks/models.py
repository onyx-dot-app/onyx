from datetime import datetime
from enum import Enum
from typing import Annotated
from typing import Any

from pydantic import BaseModel
from pydantic import Field
from pydantic import field_validator
from pydantic import model_validator
from pydantic import SecretStr

from onyx.db.enums import HookFailStrategy
from onyx.db.enums import HookPoint

NonEmptySecretStr = Annotated[SecretStr, Field(min_length=1)]


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class HookCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    hook_point: HookPoint
    endpoint_url: str = Field(min_length=1)
    api_key: NonEmptySecretStr | None = None
    fail_strategy: HookFailStrategy | None = None  # if None, uses HookPointSpec default
    timeout_seconds: float | None = Field(
        default=None, gt=0
    )  # if None, uses HookPointSpec default

    @field_validator("name", "endpoint_url")
    @classmethod
    def no_whitespace_only(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("cannot be whitespace-only.")
        return v


class HookUpdateRequest(BaseModel):
    name: str | None = None
    endpoint_url: str | None = None
    api_key: NonEmptySecretStr | None = None
    fail_strategy: HookFailStrategy | None = (
        None  # if None in model_fields_set, reset to spec default
    )
    timeout_seconds: float | None = Field(
        default=None, gt=0
    )  # if None in model_fields_set, reset to spec default

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> "HookUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided for an update.")
        if "name" in self.model_fields_set and not (self.name or "").strip():
            raise ValueError("name cannot be cleared.")
        if (
            "endpoint_url" in self.model_fields_set
            and not (self.endpoint_url or "").strip()
        ):
            raise ValueError("endpoint_url cannot be cleared.")
        return self


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class HookPointMetaResponse(BaseModel):
    hook_point: HookPoint
    display_name: str
    description: str
    docs_url: str | None
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    default_timeout_seconds: float
    default_fail_strategy: HookFailStrategy
    fail_hard_description: str


class HookResponse(BaseModel):
    id: int
    name: str
    hook_point: HookPoint
    # Nullable to match the DB column — endpoint_url is required on creation but
    # future hook point types may not use an external endpoint (e.g. built-in handlers).
    endpoint_url: str | None
    fail_strategy: HookFailStrategy
    timeout_seconds: float  # always resolved — None from request is replaced with spec default before DB write
    is_active: bool
    creator_email: str | None
    created_at: datetime
    updated_at: datetime


class HookValidateResponse(BaseModel):
    success: bool
    error_message: str | None = None


# ---------------------------------------------------------------------------
# Health models
# ---------------------------------------------------------------------------


class HookHealthStatus(str, Enum):
    healthy = "healthy"  # green — reachable, no failures in last 1h
    degraded = "degraded"  # yellow — reachable, failures in last 1h
    unreachable = "unreachable"  # red — is_reachable=false or null


class HookFailureRecord(BaseModel):
    error_message: str | None = None
    status_code: int | None = None
    duration_ms: int | None = None
    created_at: datetime


class HookHealthResponse(BaseModel):
    status: HookHealthStatus
    recent_failures: list[HookFailureRecord] = Field(
        default_factory=list,
        description="Last 10 failures, newest first",
        max_length=10,
    )
