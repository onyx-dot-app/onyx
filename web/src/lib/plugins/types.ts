/**
 * Plugin upload and plugin detail shapes; mirror
 * `backend/onyx/skills/models.py`, `backend/onyx/integrations/plugin_needs.py`
 * and `backend/onyx/server/features/skill/models.py`.
 */

/** A part of a Claude Code or Codex plugin that Onyx does not use. */
export type PluginUnusedPart =
  | "commands"
  | "agents"
  | "hooks"
  | "lsp_servers"
  | "output_styles"
  | "bin"
  | "themes"
  | "monitors";

export interface PluginAuthor {
  name: string | null;
  email: string | null;
  url: string | null;
}

export interface PluginManifest {
  name: string;
  version: string | null;
  description: string | null;
  author: PluginAuthor | null;
  homepage: string | null;
  repository: string | null;
  license: string | null;
  keywords: string[];
  unused_parts: PluginUnusedPart[];
}

/** The first five are the states of the one integration a need matches. */
export type PluginNeedState =
  | "on"
  | "turn_on"
  | "sign_in"
  | "no_access"
  | "turned_off"
  | "not_added"
  | "more_than_one"
  | "not_supported";

/** One MCP server a plugin names, with its state for the user. */
export interface PluginNeed {
  kind: "mcp";
  /** The server key in .mcp.json. */
  name: string;
  /** The normalized server URL; null for a local server. */
  url: string | null;
  /** The `type` of the entry, "stdio" for a local command, or null. */
  transport: string | null;
  supported: boolean;
  state: PluginNeedState;
  /** Set only when exactly one integration matches. */
  integration_id: number | null;
}

export interface PluginSkillSummary {
  /** The skill's folder in the bundle, such as "skills/review". */
  path: string;
  name: string;
  description: string;
}

/** The version of a plugin that the user runs. */
export interface PluginDetail {
  manifest: PluginManifest | null;
  skills: PluginSkillSummary[];
  needs: PluginNeed[];
}

export interface PluginUploadSkill extends PluginSkillSummary {
  warnings: string[];
}

interface PluginUploadTargetBase {
  plugin_name: string;
  version_number: number;
}

/** Where a save puts the upload. */
export type PluginUploadTarget =
  | (PluginUploadTargetBase & { kind: "new_version"; plugin_id: string })
  | (PluginUploadTargetBase & { kind: "new_plugin"; plugin_id: null });

export interface PluginUploadPreview {
  name: string;
  /** The version in plugin.json, as written. */
  version: string | null;
  description: string | null;
  manifest: PluginManifest;
  skills: PluginUploadSkill[];
  needs: PluginNeed[];
  unused_parts: PluginUnusedPart[];
  warnings: string[];
  target: PluginUploadTarget;
}
