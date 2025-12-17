from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class PlanType(str, Enum):
    MONTHLY = "monthly"
    ANNUAL = "annual"


class LicenseSource(str, Enum):
    AUTO_FETCH = "auto_fetch"
    MANUAL_UPLOAD = "manual_upload"


class LicensePayload(BaseModel):
    """The payload portion of a signed license."""

    version: str
    tenant_id: str
    organization_name: str | None = None
    issued_at: datetime
    expires_at: datetime
    seats: int
    plan_type: PlanType
    billing_cycle: str | None = None
    grace_period_days: int = 30
    stripe_subscription_id: str | None = None
    stripe_customer_id: str | None = None


class LicenseData(BaseModel):
    """Full signed license structure."""

    payload: LicensePayload
    signature: str


class LicenseMetadata(BaseModel):
    """Cached license metadata stored in Redis."""

    tenant_id: str
    organization_name: str | None = None
    seats: int
    used_seats: int
    plan_type: PlanType
    issued_at: datetime
    expires_at: datetime
    grace_period_end: datetime | None = None
    status: str
    source: LicenseSource | None = None
    stripe_subscription_id: str | None = None


class LicenseStatusResponse(BaseModel):
    """Response for license status API."""

    has_license: bool
    seats: int = 0
    used_seats: int = 0
    plan_type: PlanType | None = None
    issued_at: datetime | None = None
    expires_at: datetime | None = None
    grace_period_end: datetime | None = None
    status: str | None = None
    source: LicenseSource | None = None


class LicenseResponse(BaseModel):
    """Response after license fetch/upload."""

    success: bool
    message: str | None = None
    license: LicensePayload | None = None


class LicenseUploadResponse(BaseModel):
    """Response after license upload."""

    success: bool
    message: str | None = None


class SeatUsageResponse(BaseModel):
    """Response for seat usage API."""

    total_seats: int
    used_seats: int
    available_seats: int
