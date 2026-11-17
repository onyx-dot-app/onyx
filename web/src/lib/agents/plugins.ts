import type {
  AgentPluginInput,
  AgentPluginLink,
  LinkValue,
} from "@/lib/agents/types";
import type {
  AgentCatalogIntegration,
  IntegrationAction,
  PolicyValue,
} from "@/lib/integrations/types";

/** One plugin of the agent editor form. `actions` holds only the actions
 * with a setting of their own. */
export interface AgentPluginDraft {
  plugin_id: string;
  plugin_name: string;
  default: LinkValue;
  actions: Record<string, LinkValue>;
}

export function draftFromLink(link: AgentPluginLink): AgentPluginDraft {
  return {
    plugin_id: link.plugin_id,
    plugin_name: link.plugin_name,
    default: link.action_settings.default ?? "inherit",
    actions: Object.fromEntries(
      Object.entries(link.action_settings.actions ?? {}).filter(
        ([, value]) => value !== "inherit"
      )
    ),
  };
}

/** The request shape, with each inherit key left out. */
export function toPluginInput(draft: AgentPluginDraft): AgentPluginInput {
  const actions = Object.fromEntries(
    Object.entries(draft.actions).filter(([, value]) => value !== "inherit")
  );
  return {
    plugin_id: draft.plugin_id,
    action_settings: {
      ...(draft.default !== "inherit" && { default: draft.default }),
      ...(Object.keys(actions).length > 0 && { actions }),
    },
  };
}

export type LockReason = "adminBlocked" | "adminFinal";

/** Why the agent cannot set Allow on the action, or null when it can. */
export function lockReason(
  integration: AgentCatalogIntegration,
  action: IntegrationAction
): LockReason | null {
  if (action.effective_admin_policy === "blocked") return "adminBlocked";
  if (!integration.users_can_save_always_allow) return "adminFinal";
  return null;
}

export type SettingSource = "integration" | "agentDefault" | "agent";

export interface EffectiveSetting {
  policy: PolicyValue;
  source: SettingSource;
}

/** The value that applies to the action for this agent, before the saved
 * choice of a user. Follows the backend policy order. */
export function effectiveSetting(
  integration: AgentCatalogIntegration,
  action: IntegrationAction,
  draft: AgentPluginDraft
): EffectiveSetting {
  const own = draft.actions[action.key];
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
