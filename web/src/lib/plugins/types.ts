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

export type PluginNeedState =
  | "on"
  | "turn_on"
  | "sign_in"
  | "no_access"
  | "turned_off"
  | "not_added"
  | "more_than_one"
  | "not_supported";

export type PluginNeedUrlProblem = "variable" | "credential" | "invalid";

export interface PluginNeed {
  kind: "mcp";
  name: string;
  url: string | null;
  transport: string | null;
  url_problem: PluginNeedUrlProblem | null;
  supported: boolean;
  state: PluginNeedState;
  integration_id: number | null;
}

export interface PluginSkillSummary {
  path: string;
  name: string;
  description: string;
}

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
  /** A new plugin whose name the user's "My uploads" already holds. */
  name_taken: boolean;
}

export type PluginUploadTarget =
  | (PluginUploadTargetBase & { kind: "new_version"; plugin_id: string })
  | (PluginUploadTargetBase & { kind: "new_plugin"; plugin_id: null });

export interface PluginUploadPreview {
  manifest: PluginManifest;
  skills: PluginUploadSkill[];
  needs: PluginNeed[];
  warnings: string[];
  target: PluginUploadTarget;
  will_enable: boolean;
  name_conflicts: string[];
  /** The files equal the current version's files, so a save adds no version. */
  unchanged: boolean;
}
