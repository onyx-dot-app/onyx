import {
  draftFromLink,
  effectiveSetting,
  toPluginInput,
  type AgentPluginDraft,
} from "@/lib/agents/plugins";
import type {
  AgentCatalogIntegration,
  IntegrationAction,
} from "@/lib/integrations/types";

function draft(overrides: Partial<AgentPluginDraft> = {}): AgentPluginDraft {
  return {
    plugin_id: "p1",
    plugin_name: "Linear",
    default: "inherit",
    actions: {},
    ...overrides,
  };
}

const action: IntegrationAction = {
  key: "create_issue",
  display_name: "Create issue",
  description: null,
  read_only: false,
  default_policy: "ask",
  admin_policy: null,
  effective_admin_policy: "ask",
  always_asks: false,
};

const integration: AgentCatalogIntegration = {
  id: 1,
  name: "Linear",
  kind: "mcp_server",
  shape: "mcp_server",
  users_can_save_always_allow: true,
  actions: [action],
};

test("loads stored settings and keeps inherit entries", () => {
  expect(
    draftFromLink({
      plugin_id: "p1",
      plugin_name: "Linear",
      action_settings: {
        default: "blocked",
        actions: { a: "inherit", b: "allow" },
      },
    })
  ).toEqual(
    draft({ default: "blocked", actions: { a: "inherit", b: "allow" } })
  );
  expect(
    draftFromLink({
      plugin_id: "p1",
      plugin_name: "Linear",
      action_settings: {},
    })
  ).toEqual(draft());
});

test("a migrated link saves back unchanged", () => {
  const migrated = {
    plugin_id: "p1",
    plugin_name: "Linear",
    action_settings: {
      default: "blocked" as const,
      actions: { hello: "inherit" as const },
    },
  };
  expect(toPluginInput(draftFromLink(migrated))).toEqual({
    plugin_id: "p1",
    action_settings: { default: "blocked", actions: { hello: "inherit" } },
  });
});

test("leaves an inherit default out of the request", () => {
  expect(toPluginInput(draft())).toEqual({
    plugin_id: "p1",
    action_settings: {},
  });
  expect(toPluginInput(draft({ actions: { a: "blocked" } }))).toEqual({
    plugin_id: "p1",
    action_settings: { actions: { a: "blocked" } },
  });
  expect(
    toPluginInput(draft({ default: "ask", actions: { a: "allow" } }))
  ).toEqual({
    plugin_id: "p1",
    action_settings: { default: "ask", actions: { a: "allow" } },
  });
});

test("follows the backend order for the setting that applies", () => {
  const blockedByAdmin = {
    ...action,
    effective_admin_policy: "blocked" as const,
  };
  const finalIntegration = {
    ...integration,
    users_can_save_always_allow: false,
  };
  expect(effectiveSetting(integration, action, draft())).toEqual({
    policy: "ask",
    source: "integration",
  });
  expect(
    effectiveSetting(integration, action, draft({ default: "blocked" }))
  ).toEqual({ policy: "blocked", source: "agentDefault" });
  expect(
    effectiveSetting(
      integration,
      action,
      draft({ default: "blocked", actions: { create_issue: "allow" } })
    )
  ).toEqual({ policy: "allow", source: "agent" });
  expect(
    effectiveSetting(
      finalIntegration,
      action,
      draft({ actions: { create_issue: "allow" } })
    )
  ).toEqual({ policy: "ask", source: "integration" });
  expect(
    effectiveSetting(
      integration,
      blockedByAdmin,
      draft({ actions: { create_issue: "ask" } })
    )
  ).toEqual({ policy: "blocked", source: "integration" });
});

test("an action named like an Object member uses the default", () => {
  const named = { ...action, key: "constructor" };
  expect(effectiveSetting(integration, named, draft())).toEqual({
    policy: "ask",
    source: "integration",
  });
});
