from pydantic import BaseModel

from onyx.configs.constants import NotificationType
from onyx.server.settings.models import GatingType


class CheckoutSessionCreationRequest(BaseModel):
    quantity: int


class CreateTenantRequest(BaseModel):
    tenant_id: str
    initial_admin_email: str


class ProductGatingRequest(BaseModel):
    tenant_id: str
    product_gating: GatingType
    notification: NotificationType | None = None


class BillingInformation(BaseModel):
    seats: int
    subscription_status: str
    billing_start: str
    billing_end: str
    payment_method_enabled: bool


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
