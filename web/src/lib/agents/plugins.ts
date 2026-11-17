import type { AgentPluginInput, AgentPluginLink } from "@/lib/agents/types";
import type {
  AgentCatalogIntegration,
  IntegrationAction,
  LinkValue,
  PolicyValue,
} from "@/lib/integrations/types";

/** One plugin of the agent editor form. `actions` holds the actions with a
 * setting of their own; an action with no entry uses `default`. An entry of
 * `inherit` is not the same as no entry: a migrated agent has a `blocked`
 * default with `inherit` for the tools it used. */
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
    actions: { ...link.action_settings.actions },
  };
}

export function toPluginInput(draft: AgentPluginDraft): AgentPluginInput {
  return {
    plugin_id: draft.plugin_id,
    action_settings: {
      ...(draft.default !== "inherit" && { default: draft.default }),
      ...(Object.keys(draft.actions).length > 0 && { actions: draft.actions }),
    },
  };
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

const STRICTNESS: Record<PolicyValue, number> = {
  allow: 0,
  ask: 1,
  blocked: 2,
};

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

/** The plugin of the agent whose setting is stricter for the action than
 * the setting of `draft`, if any. The backend applies the strictest link of
 * the plugins that hold the integration. */
export function stricterPlugin(
  integration: AgentCatalogIntegration,
  action: IntegrationAction,
  draft: AgentPluginDraft,
  others: readonly AgentPluginDraft[]
): { draft: AgentPluginDraft; setting: EffectiveSetting } | null {
  let strictest: { draft: AgentPluginDraft; setting: EffectiveSetting } | null =
    null;
  let floor = STRICTNESS[effectiveSetting(integration, action, draft).policy];
  for (const other of others) {
    const setting = effectiveSetting(integration, action, other);
    if (STRICTNESS[setting.policy] > floor) {
      strictest = { draft: other, setting };
      floor = STRICTNESS[setting.policy];
    }
  }
  return strictest;
}
