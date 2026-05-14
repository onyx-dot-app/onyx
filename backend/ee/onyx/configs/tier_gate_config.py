"""Single source of truth for path-prefix → minimum tier gating.

The `tier_gate` middleware reads this map at startup, sorts entries by
prefix length (longest first), and enforces them on every request.

`Tier.BUSINESS` = Business+ tier. `Tier.ENTERPRISE` = Enterprise only.
Anything not listed is unrestricted. Longest-prefix-wins, so a nested
path can resolve to a stricter tier than its parent (e.g.
`/admin/enterprise-settings/scim` is ENTERPRISE even though
`/admin/enterprise-settings` is BUSINESS).
"""

from onyx.server.settings.models import Tier

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
    # NOTE: /manage/admin/cc-pair/{id}/sync-permissions can't be prefix-matched
    # (variable in the middle); the FE hides it in AccessTypeForm instead.
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
