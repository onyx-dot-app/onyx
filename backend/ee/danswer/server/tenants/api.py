import stripe
from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Response

from danswer.auth.users import auth_backend
from danswer.auth.users import current_admin_user
from danswer.auth.users import get_jwt_strategy
from danswer.auth.users import User
from danswer.configs.app_configs import WEB_DOMAIN
from danswer.db.engine import get_session_with_tenant
from danswer.db.notification import create_notification
from danswer.db.users import get_user_by_email
from danswer.server.settings.store import load_settings
from danswer.server.settings.store import store_settings
from danswer.utils.logger import setup_logger
from ee.danswer.auth.users import current_cloud_superuser
from ee.danswer.configs.app_configs import STRIPE_SECRET_KEY
from ee.danswer.server.tenants.access import control_plane_dep
from ee.danswer.server.tenants.billing import fetch_billing_information
from ee.danswer.server.tenants.billing import fetch_tenant_stripe_information
from ee.danswer.server.tenants.models import BillingInformation
from ee.danswer.server.tenants.models import ImpersonateRequest
from ee.danswer.server.tenants.models import ProductGatingRequest
from ee.danswer.server.tenants.user_mapping import get_tenant_id_for_email
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

stripe.api_key = STRIPE_SECRET_KEY

logger = setup_logger()
router = APIRouter(prefix="/tenants")


@router.post("/product-gating")
def gate_product(
    product_gating_request: ProductGatingRequest, _: None = Depends(control_plane_dep)
) -> None:
    """
    Gating the product means that the product is not available to the tenant.
    They will be directed to the billing page.
    We gate the product when
    1) User has ended free trial without adding payment method
    2) User's card has declined
    """
    tenant_id = product_gating_request.tenant_id
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)

    settings = load_settings()
    settings.product_gating = product_gating_request.product_gating
    store_settings(settings)

    if product_gating_request.notification:
        with get_session_with_tenant(tenant_id) as db_session:
            create_notification(None, product_gating_request.notification, db_session)

    if token is not None:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


@router.get("/billing-information", response_model=BillingInformation)
async def billing_information(
    _: User = Depends(current_admin_user),
) -> BillingInformation:
    logger.info("Fetching billing information")
    return BillingInformation(
        **fetch_billing_information(CURRENT_TENANT_ID_CONTEXTVAR.get())
    )


@router.post("/create-customer-portal-session")
async def create_customer_portal_session(_: User = Depends(current_admin_user)) -> dict:
    try:
        # Fetch tenant_id and current tenant's information
        tenant_id = CURRENT_TENANT_ID_CONTEXTVAR.get()
        stripe_info = fetch_tenant_stripe_information(tenant_id)
        stripe_customer_id = stripe_info.get("stripe_customer_id")
        if not stripe_customer_id:
            raise HTTPException(status_code=400, detail="Stripe customer ID not found")
        logger.info(stripe_customer_id)
        portal_session = stripe.billing_portal.Session.create(
            customer=stripe_customer_id,
            return_url=f"{WEB_DOMAIN}/admin/cloud-settings",
        )
        logger.info(portal_session)
        return {"url": portal_session.url}
    except Exception as e:
        logger.exception("Failed to create customer portal session")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/impersonate")
async def impersonate_user(
    impersonate_request: ImpersonateRequest,
    _: User = Depends(current_cloud_superuser),
) -> Response:
    """Allows a cloud superuser to impersonate another user by generating an impersonation JWT token"""
    tenant_id = get_tenant_id_for_email(impersonate_request.email)

    with get_session_with_tenant(tenant_id) as tenant_session:
        user_to_impersonate = get_user_by_email(
            impersonate_request.email, tenant_session
        )
        if user_to_impersonate is None:
            raise HTTPException(status_code=404, detail="User not found")
        token = await get_jwt_strategy().write_token(user_to_impersonate)

    response = await auth_backend.transport.get_login_response(token)
    response.set_cookie(
        key="fastapiusersauth",
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
    )
    return response
