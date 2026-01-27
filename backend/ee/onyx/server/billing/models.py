"""Pydantic models for the billing API."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class CreateCheckoutSessionRequest(BaseModel):
    """Request to create a Stripe checkout session."""

    billing_period: Literal["monthly", "annual"] = "monthly"
    email: str | None = None


class CreateCheckoutSessionResponse(BaseModel):
    """Response containing the Stripe checkout session URL."""

    url: str


class CreateCustomerPortalSessionRequest(BaseModel):
    """Request to create a Stripe customer portal session."""

    return_url: str | None = None


class CreateCustomerPortalSessionResponse(BaseModel):
    """Response containing the Stripe customer portal URL."""

    url: str


class BillingInformationResponse(BaseModel):
    """Billing information for the current subscription."""

    tenant_id: str
    status: str | None = None
    plan_type: str | None = None
    seats: int | None = None
    billing_period: str | None = None
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    cancel_at_period_end: bool = False
    canceled_at: datetime | None = None
    trial_start: datetime | None = None
    trial_end: datetime | None = None
    payment_method_enabled: bool = False


class SubscriptionStatusResponse(BaseModel):
    """Response when no subscription exists."""

    subscribed: bool = False


class SeatUpdateRequest(BaseModel):
    """Request to update seat count."""

    new_seat_count: int


class SeatUpdateResponse(BaseModel):
    """Response from seat update operation."""

    success: bool
    current_seats: int
    used_seats: int
    message: str | None = None


class StripePublishableKeyResponse(BaseModel):
    """Response containing the Stripe publishable key."""

    publishable_key: str
