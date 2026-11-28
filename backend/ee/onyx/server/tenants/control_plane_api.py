"""Routes the control plane calls on the data plane: product gating, tier
updates and playground usage limits. Mounted on every multi-tenant deployment,
the playground included. The billing routes in billing_api.py are not."""

from fastapi import APIRouter, Depends

from ee.onyx.server.billing.billing_cache import invalidate_billing_cache
from ee.onyx.server.tenants.access import control_plane_dep
from ee.onyx.server.tenants.models import (
    ProductGatingFullSyncRequest,
    ProductGatingRequest,
    ProductGatingResponse,
    TenantUsageLimitState,
    TierUpdateRequest,
    TierUpdateResponse,
    UsageLimitOverridesPushRequest,
    UsageLimitOverridesPushResponse,
)
from ee.onyx.server.tenants.product_gating import (
    overwrite_full_gated_set,
    store_product_gating,
)
from ee.onyx.server.tenants.tier_management import update_tenant_tier
from ee.onyx.server.tenants.usage_limit_cache import store_tenant_usage_limit_state
from onyx.utils.logger import setup_logger
from shared_configs.configs import IS_PLAYGROUND

logger = setup_logger()

router = APIRouter(prefix="/tenants")


@router.post("/product-gating")
def gate_product(
    product_gating_request: ProductGatingRequest, _: None = Depends(control_plane_dep)
) -> ProductGatingResponse:
    """
    Gating the product means that the product is not available to the tenant.
    They will be directed to the billing page.
    We gate the product when their subscription has ended.
    """
    try:
        store_product_gating(
            product_gating_request.tenant_id, product_gating_request.application_status
        )
        return ProductGatingResponse(updated=True, error=None)

    except Exception as e:
        logger.exception("Failed to gate product")
        return ProductGatingResponse(updated=False, error=str(e))


@router.post("/product-gating/full-sync")
def gate_product_full_sync(
    product_gating_request: ProductGatingFullSyncRequest,
    _: None = Depends(control_plane_dep),
) -> ProductGatingResponse:
    """
    Bulk operation to overwrite the entire gated tenant set.
    This replaces all currently gated tenants with the provided list.
    Gated tenants are not available to access the product and will be
    directed to the billing page when their subscription has ended.
    """
    try:
        overwrite_full_gated_set(product_gating_request.gated_tenant_ids)
        return ProductGatingResponse(updated=True, error=None)

    except Exception as e:
        logger.exception("Failed to gate products during full sync")
        return ProductGatingResponse(updated=False, error=str(e))


@router.post("/tier-update")
def update_tier(
    tier_update_request: TierUpdateRequest,
    _: None = Depends(control_plane_dep),
) -> TierUpdateResponse:
    try:
        update_tenant_tier(
            tier_update_request.tenant_id,
            tier_update_request.customer_tier,
            tier_update_request.trial_end,
        )
        # Drop the billing snapshot so usage-limit gating (trial API access,
        # indexing caps) sees the change now, not after the TTL backstop.
        invalidated = invalidate_billing_cache(tier_update_request.tenant_id)
    except Exception as e:
        logger.exception("Failed to apply tier update")
        return TierUpdateResponse(updated=False, error=str(e))

    if invalidated:
        return TierUpdateResponse(updated=True, error=None)
    # Reported as failed so the CP retries. The tier write is an idempotent
    # Redis SET, so a retry only re-attempts the drop.
    return TierUpdateResponse(
        updated=False,
        error="tier updated but billing cache invalidation failed",
    )


@router.post("/usage-limit-overrides")
def push_usage_limit_overrides(
    push_request: UsageLimitOverridesPushRequest,
    _: None = Depends(control_plane_dep),
) -> UsageLimitOverridesPushResponse:
    """Store a playground tenant's trial start and overrides, for example after
    sales raise a limit, so the change applies at once. Each override replaces
    the plan's amount. It is not added to it."""
    if not IS_PLAYGROUND:
        return UsageLimitOverridesPushResponse(
            updated=False,
            error="Usage limit overrides are only used on the playground",
        )
    state = TenantUsageLimitState(
        trial_start=push_request.trial_start, limits=push_request.limits
    )
    if store_tenant_usage_limit_state(push_request.tenant_id, state):
        return UsageLimitOverridesPushResponse(updated=True, error=None)
    # Reported as failed so the control plane retries. The write is idempotent.
    return UsageLimitOverridesPushResponse(
        updated=False, error="Usage limit cache write failed"
    )
