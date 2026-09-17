from datetime import datetime
from enum import Enum

from pydantic import BaseModel

from ee.onyx.utils.license_expiry import ExpiryWarningStage
from onyx.server.settings.models import ApplicationStatus


class PlanType(str, Enum):
    MONTHLY = "monthly"
    ANNUAL = "annual"


class LicenseSource(str, Enum):
    """Whether a license can be re-fetched from the control plane on its own."""

    AUTO_FETCH = "auto_fetch"
    MANUAL_UPLOAD = "manual_upload"


class CustomerTier(str, Enum):
    """Paid-tier wire format from the control plane (no COMMUNITY)."""

    BUSINESS = "BUSINESS"
    ENTERPRISE = "ENTERPRISE"


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
    customer_tier: CustomerTier | None = None
    # Older licenses omit this field, so None means not-a-trial, never
    # trial-unknown.
    trial_end: datetime | None = None

    @property
    def ends_with_trial(self) -> bool:
        """True when this license runs only as far as a trial.

        A converted subscription keeps its past trial_end but expires at the
        end of the paid period, so comparing the two distinguishes a trial
        about to lapse from a paid license about to lapse.
        """
        return self.trial_end is not None and self.trial_end >= self.expires_at

    @property
    def source(self) -> LicenseSource:
        # Only a Stripe-billed license has a customer the control plane can
        # re-issue against. Sales-issued ones are replaced by hand.
        return (
            LicenseSource.AUTO_FETCH
            if self.stripe_customer_id
            else LicenseSource.MANUAL_UPLOAD
        )

    @property
    def self_renewing(self) -> bool:
        """True when a replacement arrives without anyone doing anything."""
        return self.source == LicenseSource.AUTO_FETCH


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
    status: ApplicationStatus
    expiry_warning_stage: ExpiryWarningStage = ExpiryWarningStage.NONE
    source: LicenseSource | None = None
    stripe_subscription_id: str | None = None
    customer_tier: CustomerTier | None = None
    trial_end: datetime | None = None


class LicenseStatusResponse(BaseModel):
    """Response for license status API."""

    has_license: bool
    seats: int = 0
    used_seats: int = 0
    plan_type: PlanType | None = None
    issued_at: datetime | None = None
    expires_at: datetime | None = None
    grace_period_end: datetime | None = None
    status: ApplicationStatus | None = None
    expiry_warning_stage: ExpiryWarningStage = ExpiryWarningStage.NONE
    source: LicenseSource | None = None
    trial_end: datetime | None = None


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
