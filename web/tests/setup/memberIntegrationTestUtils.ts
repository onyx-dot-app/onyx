import type {
  IntegrationAccess,
  MemberAction,
  MemberIntegration,
} from "@/lib/integrations/types";

export function makeAccess(
  overrides: Partial<IntegrationAccess> = {}
): IntegrationAccess {
  return {
    state: "sign_in",
    installation_policy: "AVAILABLE",
    user_choice: true,
    user_enabled: true,
    owner_email: null,
    is_owner: false,
    can_manage: false,
    shared_with_everyone: true,
    ...overrides,
  };
}

export function makeMemberIntegration(
  overrides: Partial<MemberIntegration> = {}
): MemberIntegration {
  return {
    id: 1,
    kind: "mcp",
    shape: "mcp_server",
    name: "Linear",
    description: "Manage issues",
    preset_id: null,
    auth_mode: "individual",
    auth_method: "oauth2",
    credential_fields: [],
    status: { state: "not_connected", reason: null },
    access: makeAccess(),
    users_can_save_always_allow: false,
    credential_values: {},
    external_app_id: null,
    service_urls: [],
    mcp_server_id: 7,
    server_url: "https://mcp.linear.app/mcp",
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
