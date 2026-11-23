import { Tier } from "@/lib/tiers/types";

/**
 * A feature the playground (the free trial) can restrict. Mirrors
 * `PlaygroundRestrictedFeature` in `backend/onyx/server/playground.py`, and
 * the values are what `/settings` sends in `playground_restrictions`. The list
 * there is what is restricted today; it is empty off the playground.
 */
export enum PlaygroundRestrictedFeature {
  LLM_PROVIDERS = "llm_providers",
  CONTEXTUAL_RAG = "contextual_rag",
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

/**
 * The plan that includes each feature, shown as a badge so the user sees what
 * their own Onyx would include. `null` for a feature the trial simply switches
 * off. A new feature must be listed here, or the build fails.
 */
export const PLAYGROUND_FEATURE_PLAN: Record<
  PlaygroundRestrictedFeature,
  Tier | null
> = {
  [PlaygroundRestrictedFeature.LLM_PROVIDERS]: Tier.ENTERPRISE,
  [PlaygroundRestrictedFeature.CONTEXTUAL_RAG]: Tier.ENTERPRISE,
  [PlaygroundRestrictedFeature.SSO]: Tier.ENTERPRISE,
  [PlaygroundRestrictedFeature.SCIM]: Tier.ENTERPRISE,
  [PlaygroundRestrictedFeature.WHITELABEL]: Tier.ENTERPRISE,
  [PlaygroundRestrictedFeature.HOOKS]: Tier.ENTERPRISE,
  [PlaygroundRestrictedFeature.LOG_EXPORT]: Tier.ENTERPRISE,
  [PlaygroundRestrictedFeature.STANDARD_ANSWERS]: Tier.ENTERPRISE,
  [PlaygroundRestrictedFeature.ANONYMOUS_ACCESS]: null,
  [PlaygroundRestrictedFeature.LLM_GATEWAY]: null,
  [PlaygroundRestrictedFeature.SERVICE_ACCOUNT_KEYS]: null,
  [PlaygroundRestrictedFeature.EMBEDDING]: null,
};
