"""Path prefixes blocked for sub-Enterprise tiers."""

ENTERPRISE_ONLY_PATH_PREFIXES: frozenset[str] = frozenset(
    {
        "/admin/hooks",
        "/admin/token-rate-limits",
        "/scim",
    }
)
