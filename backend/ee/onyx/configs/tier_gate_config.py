"""Single source of truth for path-prefix → minimum tier gating.

The `tier_gate` middleware reads this map at startup, sorts entries by
prefix length (longest first), and enforces them on every request.

Adding or moving a feature is a one-line edit here. There is no separate
"EE-only" or "Enterprise-only" list — `Tier.BUSINESS` means
"Business+ tier", `Tier.ENTERPRISE` means "Enterprise only", and
anything not listed is unrestricted.
"""

from onyx.server.settings.models import Tier

# Path prefix → minimum tier required.
# Longest prefix wins (e.g. /admin/enterprise-settings/scim resolves to
# ENTERPRISE even though /admin/enterprise-settings is also listed).
PATH_PREFIX_MIN_TIER: dict[str, Tier] = {
    # ----- BUSINESS -----
    # Query history (admin chat session export)
    "/admin/chat-sessions": Tier.BUSINESS,
    "/admin/chat-session-history": Tier.BUSINESS,
    "/admin/query-history": Tier.BUSINESS,
    # Usage dashboards / reports
    "/admin/usage-report": Tier.BUSINESS,
    # Service-account API keys. /admin/api-key creates only
    # account_type=SERVICE_ACCOUNT keys; there is no "user-bound" variant.
    "/admin/api-key": Tier.BUSINESS,
    # Custom theming / branding (admin writes — public read is allowed
    # via /enterprise-settings, which is outside this map)
    "/admin/enterprise-settings": Tier.BUSINESS,
    # NOTE: Permission sync trigger lives at
    # /manage/admin/cc-pair/{id}/sync-permissions which can't be
    # cleanly prefix-matched (variable in the middle). Frontend hides
    # the option in AccessTypeForm; backend sync triggers remain open.
    # ----- ENTERPRISE -----
    # User Groups + RBAC
    "/manage/admin/user-group": Tier.ENTERPRISE,
    # Custom analytics (JS injection script)
    "/admin/custom-analytics": Tier.ENTERPRISE,
    # Standard answers (canned responses)
    "/manage/admin/standard-answer": Tier.ENTERPRISE,
    # Analytics endpoints
    "/analytics": Tier.ENTERPRISE,
    # Evals
    "/evals": Tier.ENTERPRISE,
    # SCIM token management — nested under enterprise-settings, longest
    # prefix wins so this resolves to ENTERPRISE not BUSINESS.
    "/admin/enterprise-settings/scim": Tier.ENTERPRISE,
    # SCIM 2.0 protocol endpoints
    "/scim": Tier.ENTERPRISE,
    # Token rate limits (usage limits)
    "/admin/token-rate-limits": Tier.ENTERPRISE,
    # Custom hooks (outbound webhooks)
    "/admin/hooks": Tier.ENTERPRISE,
}
