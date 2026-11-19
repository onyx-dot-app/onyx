import type {
  AgentIntegrationInput,
  AgentIntegrationLink,
} from "@/lib/agents/types";
import type {
  AgentCatalogIntegration,
  IntegrationAction,
  LinkValue,
  PolicyValue,
} from "@/lib/integrations/types";

/** One integration of the agent editor form. `actions` holds the actions with a
 * setting of their own; an action with no entry uses `default`. An entry of
 * `inherit` is not the same as no entry: a migrated agent has a `blocked`
 * default with `inherit` for the tools it used. */
export interface AgentIntegrationDraft {
  integration_id: number;
  integration_name: string;
  default: LinkValue;
  actions: Record<string, LinkValue>;
}

export function draftFromLink(
  link: AgentIntegrationLink
): AgentIntegrationDraft {
  return {
    integration_id: link.integration_id,
    integration_name: link.integration_name,
    default: link.action_settings.default ?? "inherit",
    actions: { ...link.action_settings.actions },
  };
}

export function toIntegrationInput(
  draft: AgentIntegrationDraft
): AgentIntegrationInput {
  return {
    integration_id: draft.integration_id,
    action_settings: {
      ...(draft.default !== "inherit" && { default: draft.default }),
      ...(Object.keys(draft.actions).length > 0 && { actions: draft.actions }),
    },
  };
}

/** The action's own setting in the draft, if any. An action key can name an
 * Object member, such as `constructor`. */
export function ownSetting(
  draft: AgentIntegrationDraft,
  key: string
): LinkValue | undefined {
  return Object.hasOwn(draft.actions, key) ? draft.actions[key] : undefined;
}

type LockReason = "adminBlocked" | "alwaysAsks" | "adminFinal";

/** Why the agent cannot set Allow on the action, or null when it can. */
export function lockReason(
  integration: AgentCatalogIntegration,
  action: IntegrationAction
): LockReason | null {
  if (action.effective_admin_policy === "blocked") return "adminBlocked";
  if (action.always_asks) return "alwaysAsks";
  if (!integration.users_can_save_always_allow) return "adminFinal";
  return null;
}

type SettingSource = "integration" | "agentDefault" | "agent";

export interface EffectiveSetting {
  policy: PolicyValue;
  source: SettingSource;
}

/** The value that applies to the action for this agent, before the saved
 * choice of a user. Follows the backend policy order. */
export function effectiveSetting(
  integration: AgentCatalogIntegration,
  action: IntegrationAction,
  draft: AgentIntegrationDraft
): EffectiveSetting {
  const own = ownSetting(draft, action.key);
  const link = own ?? draft.default;
  const source: SettingSource = own ? "agent" : "agentDefault";
  const admin = action.effective_admin_policy;
  const fromIntegration: EffectiveSetting = {
    policy: admin,
    source: "integration",
  };
  switch (link) {
    case "inherit":
      return fromIntegration;
    case "blocked":
      return { policy: "blocked", source };
    case "ask":
      return admin === "blocked" ? fromIntegration : { policy: "ask", source };
    case "allow":
      return lockReason(integration, action)
        ? fromIntegration
        : { policy: "allow", source };
  }
}
