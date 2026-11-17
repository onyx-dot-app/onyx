import type { MemberAction, MemberIntegration } from "@/lib/integrations/types";

export const LINEAR_PLUGIN_ID = "11111111-1111-4111-8111-111111111111";
export const REPORTS_PLUGIN_ID = "22222222-2222-4222-8222-222222222222";

export function makeMemberIntegration(
  overrides: Partial<MemberIntegration> = {}
): MemberIntegration {
  return {
    id: 1,
    kind: "mcp_server",
    shape: "mcp_server",
    name: "Linear",
    description: "Manage issues",
    preset_id: null,
    auth_mode: "individual",
    auth_method: "oauth2",
    credential_fields: [],
    status: { state: "not_connected", reason: null },
    plugins: [
      {
        plugin_id: LINEAR_PLUGIN_ID,
        plugin_name: "Linear",
        scope: "organization",
        owner_email: null,
        installation_policy: "AVAILABLE",
        enabled: true,
      },
    ],
    users_can_save_always_allow: false,
    ...overrides,
  };
}

export function makeMemberAction(
  overrides: Partial<MemberAction> = {}
): MemberAction {
  return {
    key: "create_issue",
    display_name: "Create issue",
    description: "Make a new issue",
    read_only: false,
    default_policy: "ask",
    admin_policy: null,
    effective_admin_policy: "ask",
    always_asks: false,
    user_policy: null,
    ...overrides,
  };
}
