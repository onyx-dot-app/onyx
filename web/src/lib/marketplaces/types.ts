import type { PluginNeed } from "@/lib/plugins/types";
import type { SkillInstallationPolicy } from "@/lib/skills/types";

export type MarketplaceScope = "personal" | "company";

export type MarketplaceEntryStatus = "ok" | "blocked" | "not_supported";

/** A reason the web translates; `reason` keeps the English text. */
export type MarketplaceReasonCode =
  | "skills_and_mcp_only"
  | "external_repository_limit"
  | "external_repository_limit_without_login";

/** A company marketplace default can be REQUIRED, as in Claude. */
export type MarketplaceDefaultPolicy = SkillInstallationPolicy;

export interface MarketplaceSource {
  repository: string;
  folder: string | null;
  ref: string | null;
}

export interface MarketplaceCreateRequest extends MarketplaceSource {
  scope: MarketplaceScope;
  /** The name that the preview read. The first sync replaces it. */
  name: string | null;
  default_installation_policy: MarketplaceDefaultPolicy | null;
}

export interface MarketplacePreviewSkill {
  name: string;
  description: string;
}

export interface MarketplacePreviewEntry {
  key: string;
  path: string | null;
  status: MarketplaceEntryStatus;
  reason: string | null;
  reason_code: MarketplaceReasonCode | null;
  description: string | null;
  version: string | null;
  skills: MarketplacePreviewSkill[];
  needs: PluginNeed[];
  warnings: string[];
}

export interface MarketplacePreview {
  repository: string;
  folder: string | null;
  ref: string | null;
  revision: string;
  status: "complete" | "failed";
  name: string | null;
  reason: string | null;
  entries: MarketplacePreviewEntry[];
  /** The caller already has this source as a personal marketplace. */
  added_personal: boolean;
  /** The organization already has this source as a company marketplace. */
  added_company: boolean;
}

export interface MarketplaceLoginUser {
  id: string;
  email: string;
}

export interface MarketplaceSummary {
  id: string;
  name: string;
  scope: MarketplaceScope;
  repository: string;
  folder: string | null;
  ref: string | null;
  /** Null for a personal marketplace, which has no default. */
  default_installation_policy: MarketplaceDefaultPolicy | null;
  /** False for a member who sees a company marketplace read-only. */
  can_manage: boolean;
  login_user: MarketplaceLoginUser | null;
  plugin_count: number;
  last_synced_at: string | null;
  last_synced_revision: string | null;
  last_error: string | null;
  syncing: boolean;
  created_at: string;
}

export interface MarketplaceEntry {
  key: string;
  path: string | null;
  status: MarketplaceEntryStatus;
  reason: string | null;
  reason_code: MarketplaceReasonCode | null;
  plugin_id: string | null;
}

export interface MarketplacePlugin {
  id: string;
  name: string;
}

export interface MarketplaceDetail extends MarketplaceSummary {
  /** False when the login user has no GitHub connection: only public repositories sync. */
  login_has_github: boolean;
  entries: MarketplaceEntry[];
  plugins: MarketplacePlugin[];
}

export interface MarketplaceList {
  marketplaces: MarketplaceSummary[];
}

export type MarketplaceKind =
  | "user_uploads"
  | "organization_library"
  | "github";

export interface SkillMarketplace {
  id: string;
  name: string;
  kind: MarketplaceKind;
  repository: string | null;
  /** A personal GitHub marketplace: only its owner gets the plugin. */
  personal: boolean;
}

export type MarketplaceSyncState =
  | "syncing"
  | "failed"
  | "not_synced"
  | "synced";
