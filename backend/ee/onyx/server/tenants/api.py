from fastapi import APIRouter

from ee.onyx.configs.app_configs import IMPERSONATION_ENABLED
from ee.onyx.server.tenants.admin_api import router as admin_router
from ee.onyx.server.tenants.anonymous_users_api import router as anonymous_users_router
from ee.onyx.server.tenants.billing_api import router as billing_router
from ee.onyx.server.tenants.control_plane_api import router as control_plane_router
from ee.onyx.server.tenants.proxy import router as proxy_router
from ee.onyx.server.tenants.team_membership_api import router as team_membership_router
from ee.onyx.server.tenants.tenant_management_api import (
    router as tenant_management_router,
)
from ee.onyx.server.tenants.user_invitations_api import (
    router as user_invitations_router,
)
from shared_configs.configs import IS_PLAYGROUND


def build_tenants_router(
    impersonation_enabled: bool = IMPERSONATION_ENABLED,
    playground: bool = IS_PLAYGROUND,
) -> APIRouter:
    """Assemble the composite tenants router.

    What a deployment does not have is not mounted, so requests 404 rather than
    reaching a handler or the auth layer: the impersonation endpoint
    (admin_router) only when its flag is set; the billing and proxy routes not
    on the playground, which has no Stripe. The routes the control plane calls
    are always mounted.

    Note: we don't add a prefix here as each sub-router already has the /tenants
    prefix.
    """
    router = APIRouter()
    router.include_router(anonymous_users_router)
    router.include_router(control_plane_router)
    router.include_router(team_membership_router)
    router.include_router(tenant_management_router)
    router.include_router(user_invitations_router)
    if not playground:
        router.include_router(billing_router)
        router.include_router(proxy_router)
    if impersonation_enabled:
        router.include_router(admin_router)
    return router


router = build_tenants_router()
