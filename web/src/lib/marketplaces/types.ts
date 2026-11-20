/**
 * GitHub marketplace API shapes; mirrors
 * `backend/onyx/server/features/skill/marketplace_models.py`.
 */

import type { PluginNeed } from "@/lib/plugins/types";
import type { OrganizationLibraryDefaultPolicy } from "@/lib/skills/types";

export type MarketplaceScope = "personal" | "company";

export type MarketplaceEntryStatus = "ok" | "blocked" | "not_supported";

/** A marketplace default cannot be REQUIRED. */
export type MarketplaceDefaultPolicy = OrganizationLibraryDefaultPolicy;

export interface MarketplaceSource {
  /** "owner/repo" or a github.com URL. */
  repository: string;
  /** The folder that holds `.claude-plugin/marketplace.json`. Null: the root. */
  folder: string | null;
  /** A branch, tag or commit. Null: the default branch. */
  ref: string | null;
}

export interface MarketplaceCreateRequest extends MarketplaceSource {
  scope: MarketplaceScope;
  /** Company only. Null: Available. */
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
  name: string | null;
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
  default_installation_policy: MarketplaceDefaultPolicy;
  /** The user whose GitHub connection reads the repository; null when gone. */
  login_user: MarketplaceLoginUser | null;
  plugin_count: number;
  last_synced_at: string | null;
  last_synced_revision: string | null;
  last_error: string | null;
  /** A sync is asked for and has not started yet. */
  sync_requested: boolean;
  /** A sync waits for a user to confirm its deletes. */
  needs_confirmation: boolean;
  created_at: string;
}

export interface MarketplaceEntry {
  key: string;
  path: string | null;
  status: MarketplaceEntryStatus;
  reason: string | null;
  plugin_id: string | null;
  plugin_name: string | null;
}

export interface MarketplacePendingDelete {
  plugin_id: string;
  entry_key: string;
  name: string;
}

export interface MarketplaceDetail extends MarketplaceSummary {
  entries: MarketplaceEntry[];
  /** Send this back to confirm the deletes. Null when nothing waits. */
  pending_delete_revision: string | null;
  pending_deletes: MarketplacePendingDelete[];
}

export interface MarketplaceList {
  marketplaces: MarketplaceSummary[];
}

export type MarketplaceKind =
  | "user_uploads"
  | "organization_library"
  | "github";

/** Where a custom skill or plugin comes from. */
export interface SkillMarketplace {
  id: string;
  name: string;
  kind: MarketplaceKind;
  /** "owner/repo" for a GitHub marketplace. */
  repository: string | null;
}

export type MarketplaceSyncState =
  | "syncing"
  | "needs_confirmation"
  | "failed"
  | "synced";
