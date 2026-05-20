"""Constants for license enforcement and per-feature tier gating.

Three related concerns live here:

1. `LICENSE_ENFORCEMENT_ALLOWED_PREFIXES` — paths that bypass the
   self-hosted `license_enforcement` middleware (auth, billing, health,
   etc.) when the license is expired/gated.
2. `MULTI_TENANT_GATING_ALLOWED_PREFIXES` — paths that bypass the
   multi-tenant cloud gate in `tenant_tracking` when a tenant's
   subscription is inactive (`gated_tenants` Redis set). Cloud uses
   subscriptions, not licenses, and has cloud-specific billing endpoints
   (e.g. Stripe publishable key) that the resubscribe flow needs.
3. `PATH_PREFIX_MIN_TIER` — minimum tier required to access a given path
   prefix. `Tier.BUSINESS` = Business+. `Tier.ENTERPRISE` = Enterprise only.
   Longest-prefix-wins, so a nested path can resolve to a stricter tier
   than its parent (e.g. `/admin/enterprise-settings/scim` is ENTERPRISE
   even though `/admin/enterprise-settings` is BUSINESS).

Import these constants in both production code and tests to ensure
consistency.
"""

from onyx.server.settings.models import Tier

# Paths that are ALWAYS accessible, even when license is expired/gated.
# These enable users to:
#   /auth - Log in/out (users can't fix billing if locked out of auth)
#   /license - Fetch, upload, or check license status
#   /health - Health checks for load balancers/orchestrators
#   /me - Basic user info needed for UI rendering
#   /settings, /enterprise-settings - View app status and branding
#   /billing - Unified billing API
#   /proxy - Self-hosted proxy endpoints (have own license-based auth)
#   /tenants/billing-* - Legacy billing endpoints (backwards compatibility)
#   /manage/users, /users - User management (needed for seat limit resolution)
#   /notifications - Needed for UI to load properly
LICENSE_ENFORCEMENT_ALLOWED_PREFIXES: frozenset[str] = frozenset(
    {
        "/auth",
        "/license",
        "/health",
        "/me",
        "/settings",
        "/enterprise-settings",
        # Billing endpoints (unified API for both MT and self-hosted)
        "/billing",
        "/admin/billing",
        # Proxy endpoints for self-hosted billing (no tenant context)
        "/proxy",
        # Legacy tenant billing endpoints (kept for backwards compatibility)
        "/tenants/billing-information",
        "/tenants/create-customer-portal-session",
        "/tenants/create-subscription-session",
        # User management - needed to remove users when seat limit exceeded
        "/manage/users",
        "/manage/admin/users",
        "/manage/admin/valid-domains",
        "/manage/admin/deactivate-user",
        "/manage/admin/delete-user",
        "/users",
        # Notifications - needed for UI to load properly
        "/notifications",
    }
)


# Paths reachable by a tenant whose subscription is inactive (cloud only).
# Strict resubscribe surface — anything not on this list returns 402. Kept
# narrow on purpose; the self-hosted allowlist above has entries that do
# not apply in cloud (seat-limit user management, `/license`, `/proxy`),
# and the cloud-only Stripe endpoints don't exist in self-hosted. Add
# entries here only if the resubscribe flow actually fails without them.
#
# Direct evidence of who calls what (web/src/components/errorPages/AccessRestrictedPage.tsx
# and SettingsProvider):
#   /api/tenants/stripe-publishable-key   — Stripe SDK init
#   /api/tenants/create-subscription-session — Stripe checkout
#   /api/tenants/create-customer-portal-session — Stripe portal (payment method update)
#   /api/tenants/billing-information — current billing state for the UI
#   /api/billing, /api/admin/billing — unified billing API
#   /api/me — basic user info needed to render the gated page
#   /api/settings — application_status flag the gated page reads
#   /api/auth — login / logout while gated
#   /health — load-balancer probes
MULTI_TENANT_GATING_ALLOWED_PREFIXES: frozenset[str] = frozenset(
    {
        "/auth",
        "/health",
        "/me",
        "/settings",
        "/billing",
        "/admin/billing",
        "/tenants/billing-information",
        "/tenants/create-customer-portal-session",
        "/tenants/create-subscription-session",
        "/tenants/stripe-publishable-key",
    }
)


PATH_PREFIX_MIN_TIER: dict[str, Tier] = {
    # ----- BUSINESS -----
    "/admin/chat-sessions": Tier.BUSINESS,
    "/admin/chat-session-history": Tier.BUSINESS,
    "/admin/query-history": Tier.BUSINESS,
    "/admin/usage-report": Tier.BUSINESS,
    "/analytics/admin": Tier.BUSINESS,  # query/user/onyxbot/persona analytics
    "/admin/api-key": Tier.BUSINESS,  # service-account keys (no user-bound variant)
    "/admin/enterprise-settings": Tier.BUSINESS,  # admin writes; public /enterprise-settings stays open
    "/manage/admin/user-group": Tier.BUSINESS,  # groups + RBAC (Curator roles, group-scoped access)
    # ----- ENTERPRISE -----
    "/admin/enterprise-settings/custom-analytics-script": Tier.ENTERPRISE,  # JS injection
    "/admin/enterprise-settings/scim": Tier.ENTERPRISE,  # SCIM token mgmt
    "/manage/admin/standard-answer": Tier.ENTERPRISE,
    "/admin/token-rate-limits": Tier.ENTERPRISE,
    "/admin/hooks": Tier.ENTERPRISE,  # outbound webhooks
    "/analytics": Tier.ENTERPRISE,  # non-admin analytics (e.g. assistant stats)
    "/evals": Tier.ENTERPRISE,
    "/scim": Tier.ENTERPRISE,  # SCIM protocol
}
