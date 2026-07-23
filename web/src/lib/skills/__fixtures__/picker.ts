import type {
  ExternalAppType,
  ExternalAppUserResponse,
} from "@/app/craft/v1/apps/registry";
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
    author_user_id: null,
    author_email: null,
    owner: null,
    ownership_vacant: false,
    created_at: null,
    updated_at: null,
    user_shares: [],
    group_shares: [],
    public_permission: null,
    user_permission: "VIEWER",
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
    author_user_id: null,
    author_email: null,
    owner: null,
    ownership_vacant: true,
    created_at: null,
    updated_at: null,
    user_shares: [],
    group_shares: [],
    public_permission: "VIEWER",
    user_permission: "VIEWER",
    ...over,
  };
}

export function appFixture(
  over: Partial<ExternalAppUserResponse> & {
    app_type: ExternalAppType;
    id: number;
  }
): ExternalAppUserResponse {
  return {
    name: `App ${over.id}`,
    credential_keys: ["token"],
    credential_values: over.authenticated === false ? {} : { token: "***" },
    authenticated: true,
    supports_oauth: false,
    ...over,
  };
}
