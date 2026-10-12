# How long a computed edit plan can be applied.
EDIT_PLAN_TTL_SECONDS = 24 * 60 * 60
# How long an apply holds its plan. Longer than an apply with its
# validation; a crashed apply frees the plan when it expires.
EDIT_PLAN_APPLY_CLAIM_TTL_SECONDS = 15 * 60
