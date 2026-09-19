"""Constants for multi-tenant cloud subscription gating.

Cloud-only. Self-hosted licensing lives in `license_enforcement_config.py`
and is unrelated — do NOT merge the two surfaces.

Consumed by `tenant_tracking` middleware. When a tenant is in the
`gated_tenants` Redis set (control-plane marks `application_status =
GATED_ACCESS` on trial expiry / payment failure), every request whose
path is NOT in the allowlist below returns 402 SUBSCRIPTION_INACTIVE.
"""

# Paths reachable by a tenant whose subscription is inactive. Strict —
# anything not on this list returns 402. Direct evidence of who calls what
# comes from `web/src/components/errorPages/AccessRestrictedPage.tsx` and
# the `SettingsProvider` / `useSettings` hook:
#
#   /tenants/stripe-publishable-key      — Stripe SDK init
#   /tenants/create-subscription-session — Stripe checkout
#   /tenants/create-customer-portal-session — Stripe portal (payment method)
#   /tenants/billing-information         — current billing state for the UI
#   /billing, /admin/billing             — unified billing API
#   /me                                  — basic user info for the gated page
#   /settings                            — application_status flag the FE reads
#   /auth                                — login / logout while gated
#   /health                              — load-balancer probes
#
# Add entries only when the resubscribe flow actually fails without them.
MULTI_TENANT_GATING_ALLOWED_PREFIXES: frozenset[str] = frozenset(
    {
        "/auth",
        "/health",
        "/me",
        "/settings",
        "/enterprise-settings",
        "/billing",
        "/admin/billing",
        "/tenants/billing-information",
        "/tenants/create-customer-portal-session",
        "/tenants/create-subscription-session",
        "/tenants/stripe-publishable-key",
    }
)
