import type {
  ExternalAppType,
  ExternalAppUserResponse,
} from "@/app/craft/v1/apps/registry";
import type {
  BuiltinSkill,
  CustomSkill,
} from "@/refresh-pages/admin/SkillsPage/interfaces";

export function builtinFixture(over: Partial<BuiltinSkill> = {}): BuiltinSkill {
  return {
    source: "builtin",
    slug: "pptx",
    name: "PPTX",
    description: "Build PowerPoint decks.",
    is_available: true,
    unavailable_reason: null,
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
    is_public: true,
    is_personal: false,
    enabled: true,
    author_user_id: null,
    author_email: null,
    created_at: null,
    updated_at: null,
    granted_group_ids: [],
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
    ...over,
  };
}
