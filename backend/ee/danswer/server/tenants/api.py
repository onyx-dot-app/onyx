import stripe
from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException

from danswer.auth.users import current_admin_user
from danswer.auth.users import User
from danswer.configs.app_configs import MULTI_TENANT
from danswer.configs.app_configs import WEB_DOMAIN
from danswer.db.engine import get_session_with_tenant
from danswer.db.notification import create_notification
from danswer.server.settings.store import load_settings
from danswer.server.settings.store import store_settings
from danswer.setup import setup_danswer
from danswer.utils.logger import setup_logger
from ee.danswer.configs.app_configs import STRIPE_SECRET_KEY
from ee.danswer.server.tenants.access import control_plane_dep
from ee.danswer.server.tenants.billing import fetch_billing_information
from ee.danswer.server.tenants.billing import fetch_tenant_stripe_information
from ee.danswer.server.tenants.models import BillingInformation
from ee.danswer.server.tenants.models import CreateTenantRequest
from ee.danswer.server.tenants.models import ProductGatingRequest
from ee.danswer.server.tenants.provisioning import add_users_to_tenant
from ee.danswer.server.tenants.provisioning import ensure_schema_exists
from ee.danswer.server.tenants.provisioning import run_alembic_migrations
from ee.danswer.server.tenants.provisioning import user_owns_a_tenant
from shared_configs.configs import CURRENT_TENANT_ID_CONTEXTVAR


stripe.api_key = STRIPE_SECRET_KEY

logger = setup_logger()
router = APIRouter(prefix="/tenants")


@router.post("/create")
def create_tenant(
    create_tenant_request: CreateTenantRequest, _: None = Depends(control_plane_dep)
) -> dict[str, str]:
    if not MULTI_TENANT:
        raise HTTPException(status_code=403, detail="Multi-tenancy is not enabled")

    tenant_id = create_tenant_request.tenant_id
    email = create_tenant_request.initial_admin_email
    token = None

    if user_owns_a_tenant(email):
        raise HTTPException(
            status_code=409, detail="User already belongs to an organization"
        )

    try:
        if not ensure_schema_exists(tenant_id):
            logger.info(f"Created schema for tenant {tenant_id}")
        else:
            logger.info(f"Schema already exists for tenant {tenant_id}")

        token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
        run_alembic_migrations(tenant_id)

        with get_session_with_tenant(tenant_id) as db_session:
            setup_danswer(db_session)

        add_users_to_tenant([email], tenant_id)

        return {
            "status": "success",
            "message": f"Tenant {tenant_id} created successfully",
        }
    except Exception as e:
        logger.exception(f"Failed to create tenant {tenant_id}: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to create tenant: {str(e)}"
        )
    finally:
        if token is not None:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


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
