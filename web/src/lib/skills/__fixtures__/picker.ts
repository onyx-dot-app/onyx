import type {
  ExternalAppType,
  ExternalAppUserResponse,
} from "@/app/craft/v1/apps/registry";
import type { BuiltinSkill, CustomSkill } from "@/lib/skills/types";

export function builtinFixture(over: Partial<BuiltinSkill> = {}): BuiltinSkill {
  return {
    source: "builtin",
    id: "builtin-1",
    slug: "pptx",
    name: "PPTX",
    description: "Build PowerPoint decks.",
    is_available: true,
    unavailable_reason: null,
    is_personal: false,
    enabled: null,
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
    slug: "report-writer",
    name: "Report Writer",
    description: "Draft a structured report from notes.",
    is_available: null,
    unavailable_reason: null,
    is_personal: false,
    enabled: true,
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
    slug: string;
  }
): ExternalAppUserResponse {
  return {
    id: over.slug.length,
    name: over.slug,
    description: `${over.slug} integration`,
    credential_keys: ["token"],
    credential_values: over.authenticated === false ? {} : { token: "***" },
    authenticated: true,
    supports_oauth: false,
    ...over,
  };
}
