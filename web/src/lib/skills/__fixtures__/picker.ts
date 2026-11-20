import type { ExternalAppType } from "@/app/craft/v1/apps/registry";
import type { CraftApp, CraftMcpServer } from "@/lib/integrations/craft";
import type { BuiltinSkill, CustomSkill } from "@/lib/skills/types";

export function builtinFixture(over: Partial<BuiltinSkill> = {}): BuiltinSkill {
  return {
    source: "builtin",
    id: "builtin-1",
    name: "pptx",
    description: "Build PowerPoint decks.",
    is_available: true,
    unavailable_reason: null,
    is_valid: true,
    is_personal: false,
    enabled: true,
    can_toggle: false,
    installation_policy: "AVAILABLE",
    default_installation_policy: "AVAILABLE",
    can_delete: true,
    required_for_user: false,
    author_user_id: null,
    author_email: null,
    owner: null,
    ownership_vacant: false,
    created_at: null,
    updated_at: null,
    user_shares: [],
    group_shares: [],
    group_summaries: [],
    public_permission: null,
    user_permission: "VIEWER",
    member_visible: true,
    name_held_by: [],
    current_version_id: null,
    current_version_number: null,
    published_version_number: null,
    pending_version_number: null,
    kind: "skill",
    available_count: 0,
    needed_count: 0,
    plugin: null,
    marketplace: null,
    content_locked: false,
    ...over,
  };
}

export function customFixture(over: Partial<CustomSkill> = {}): CustomSkill {
  return {
    source: "custom",
    id: "custom-1",
    name: "report-writer",
    description: "Draft a structured report from notes.",
    is_available: null,
    unavailable_reason: null,
    is_valid: true,
    is_personal: false,
    enabled: true,
    can_toggle: true,
    installation_policy: "AVAILABLE",
    default_installation_policy: "AVAILABLE",
    can_delete: true,
    required_for_user: false,
    author_user_id: null,
    author_email: null,
    owner: null,
    ownership_vacant: true,
    created_at: null,
    updated_at: null,
    user_shares: [],
    group_shares: [],
    group_summaries: [],
    public_permission: "VIEWER",
    user_permission: "VIEWER",
    member_visible: true,
    name_held_by: [],
    current_version_id: null,
    current_version_number: null,
    published_version_number: null,
    pending_version_number: null,
    kind: "skill",
    available_count: 0,
    needed_count: 0,
    plugin: null,
    marketplace: null,
    content_locked: false,
    ...over,
  };
}

export function appFixture(
  over: Partial<CraftApp> & {
    app_type: ExternalAppType;
    id: number;
  }
): CraftApp {
  return {
    name: `App ${over.id}`,
    integration_id: over.id,
    authenticated: true,
    supports_oauth: false,
    ...over,
  };
}

export function mcpServerFixture(
  over: Partial<CraftMcpServer> & { id: number }
): CraftMcpServer {
  return {
    name: `MCP ${over.id}`,
    server_url: `https://mcp-${over.id}.example.com/mcp`,
    craft_connected: true,
    ...over,
  };
}
