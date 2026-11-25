/**
 * A feature the playground (the free trial) can restrict. Mirrors
 * `PlaygroundRestrictedFeature` in `backend/onyx/server/playground.py`, and
 * the values are what `/settings` sends in `playground_restrictions`. The list
 * there is what is restricted today; it is empty off the playground.
 */
export enum PlaygroundRestrictedFeature {
  LLM_PROVIDERS = "llm_providers",
  SSO = "sso",
  SCIM = "scim",
  WHITELABEL = "whitelabel",
  HOOKS = "hooks",
  LOG_EXPORT = "log_export",
  STANDARD_ANSWERS = "standard_answers",
  ANONYMOUS_ACCESS = "anonymous_access",
  LLM_GATEWAY = "llm_gateway",
  SERVICE_ACCOUNT_KEYS = "service_account_keys",
  EMBEDDING = "embedding",
}

/** Why a feature is restricted: picks the one line the notice shows. */
export enum PlaygroundRestrictionReason {
  /** The playground runs on our model keys so the user can try the features. */
  OWN_KEYS = "own_keys",
  /** An Enterprise feature, shown but not configurable on the trial. */
  ENTERPRISE = "enterprise",
  /** Simply switched off on the trial. */
  SWITCHED_OFF = "switched_off",
}

/**
 * The reason for each feature. A new feature must be listed here, or the
 * build fails.
 */
export const PLAYGROUND_FEATURE_REASON: Record<
  PlaygroundRestrictedFeature,
  PlaygroundRestrictionReason
> = {
  [PlaygroundRestrictedFeature.LLM_PROVIDERS]:
    PlaygroundRestrictionReason.OWN_KEYS,
  [PlaygroundRestrictedFeature.SSO]: PlaygroundRestrictionReason.ENTERPRISE,
  [PlaygroundRestrictedFeature.SCIM]: PlaygroundRestrictionReason.ENTERPRISE,
  [PlaygroundRestrictedFeature.WHITELABEL]:
    PlaygroundRestrictionReason.ENTERPRISE,
  [PlaygroundRestrictedFeature.HOOKS]: PlaygroundRestrictionReason.ENTERPRISE,
  [PlaygroundRestrictedFeature.LOG_EXPORT]:
    PlaygroundRestrictionReason.ENTERPRISE,
  [PlaygroundRestrictedFeature.STANDARD_ANSWERS]:
    PlaygroundRestrictionReason.ENTERPRISE,
  [PlaygroundRestrictedFeature.ANONYMOUS_ACCESS]:
    PlaygroundRestrictionReason.SWITCHED_OFF,
  [PlaygroundRestrictedFeature.LLM_GATEWAY]:
    PlaygroundRestrictionReason.SWITCHED_OFF,
  [PlaygroundRestrictedFeature.SERVICE_ACCOUNT_KEYS]:
    PlaygroundRestrictionReason.SWITCHED_OFF,
  [PlaygroundRestrictedFeature.EMBEDDING]: PlaygroundRestrictionReason.OWN_KEYS,
};
