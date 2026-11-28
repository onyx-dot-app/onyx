from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, field_validator

from ee.onyx.server.license.models import CustomerTier
from onyx.db.usage import UsageType
from onyx.server.settings.models import ApplicationStatus
from onyx.utils.logger import setup_logger

logger = setup_logger()


class CheckoutSessionCreationRequest(BaseModel):
    quantity: int


class CreateTenantRequest(BaseModel):
    tenant_id: str
    initial_admin_email: str


class ProductGatingRequest(BaseModel):
    tenant_id: str
    application_status: ApplicationStatus


class ProductGatingFullSyncRequest(BaseModel):
    gated_tenant_ids: list[str]


class TenantUsageLimitState(BaseModel):
    """What the control plane says about one playground tenant's limits."""

    # When the trial started. Periods that count from the trial start begin here.
    trial_start: datetime | None = None
    # Overrides by usage type, for example {"llm_cost_cents": 10000}. Each one
    # replaces the plan's amount. It is not added to it.
    limits: dict[UsageType, int] = {}

    @field_validator("limits", mode="before")
    @classmethod
    def _drop_unknown_usage_types(cls, raw: object) -> object:
        """The control plane may know usage types this version does not. Drop
        those, so the known overrides still apply."""
        if not isinstance(raw, dict):
            return raw
        known = {usage_type.value for usage_type in UsageType}
        kept: dict[str, object] = {}
        unknown: list[str] = []
        for key, value in raw.items():
            name = key.value if isinstance(key, UsageType) else str(key)
            if name in known:
                kept[name] = value
            else:
                unknown.append(name)
        if unknown:
            logger.warning(
                "Ignoring unknown usage limit overrides: %s", sorted(unknown)
            )
        return kept


class UsageLimitOverridesPushRequest(TenantUsageLimitState):
    tenant_id: str


class UsageLimitOverridesPushResponse(BaseModel):
    updated: bool
    error: str | None


class TierUpdateRequest(BaseModel):
    tenant_id: str
    customer_tier: CustomerTier
    trial_end: datetime | None = None


class TierUpdateResponse(BaseModel):
    updated: bool
    error: str | None


class SubscriptionStatusResponse(BaseModel):
    subscribed: bool
    customer_tier: CustomerTier | None = None


class BillingInformation(BaseModel):
    stripe_subscription_id: str
    status: str
    current_period_start: datetime
    current_period_end: datetime
    number_of_seats: int
    cancel_at_period_end: bool
    canceled_at: datetime | None
    trial_start: datetime | None
    trial_end: datetime | None
    seats: int
    payment_method_enabled: bool
    customer_tier: CustomerTier | None = None


class CreateCheckoutSessionRequest(BaseModel):
    billing_period: Literal["monthly", "annual"] = "monthly"
    seats: int | None = None
    email: str | None = None


class CheckoutSessionCreationResponse(BaseModel):
    id: str


class ImpersonateRequest(BaseModel):
    email: str


class TenantCreationPayload(BaseModel):
    tenant_id: str
    email: str
    referral_source: str | None = None


class TenantDeletionPayload(BaseModel):
    tenant_id: str
    email: str


class AnonymousUserPath(BaseModel):
    anonymous_user_path: str | None


class ProductGatingResponse(BaseModel):
    updated: bool
    error: str | None


class StripeCheckoutSessionResult(BaseModel):
    # url is always set on success; sessionId is null for the past_due/unpaid
    # payment-method-update portal response.
    session_id: str | None = None
    url: str | None = None
    requires_payment_method_update: bool = False


class SubscriptionSessionResponse(BaseModel):
    sessionId: str | None = None
    url: str | None = None
    requires_payment_method_update: bool = False


class CreateSubscriptionSessionRequest(BaseModel):
    """Request to create a subscription checkout session."""

    billing_period: Literal["monthly", "annual"] = "monthly"


class SignUpDomainState(str, Enum):
    """The control plane's answer to a playground sign-up (`POST /sign-up-domain`)."""

    NEW = "new"
    EMAIL_USED = "email_used"
    ACTIVE_TENANT = "active_tenant"
    LIMIT_REACHED = "limit_reached"


class TenantByDomainResponse(BaseModel):
    tenant_id: str
    number_of_users: int
    creator_email: str


class TenantByDomainRequest(BaseModel):
    email: str


class RequestInviteRequest(BaseModel):
    tenant_id: str


class RequestInviteResponse(BaseModel):
    success: bool
    message: str


class PendingUserSnapshot(BaseModel):
    email: str


class ApproveUserRequest(BaseModel):
    email: str


class StripePublishableKeyResponse(BaseModel):
    publishable_key: str
