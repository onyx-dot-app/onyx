from fastapi import APIRouter

from ee.onyx.server.tenants.admin_api import router as admin_router
from ee.onyx.server.tenants.anonymous_users_api import router as anonymous_users_router
from ee.onyx.server.tenants.billing_api import router as billing_router
from ee.onyx.server.tenants.team_membership_api import router as team_membership_router
from ee.onyx.server.tenants.tenant_management_api import (
    router as tenant_management_router,
)
from ee.onyx.server.tenants.user_invitations_api import (
    router as user_invitations_router,
)

# Create a main router to include all sub-routers
# Note: We don't add a prefix here as each router already has the /tenants prefix
router = APIRouter()

# Include all the individual routers
router.include_router(admin_router)
router.include_router(anonymous_users_router)
router.include_router(billing_router)
router.include_router(team_membership_router)
router.include_router(tenant_management_router)
router.include_router(user_invitations_router)
