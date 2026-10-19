import type { MemberPlugin } from "@/lib/plugins/member";

export type PluginStatus = "active" | "issues" | "inactive";

export function memberPluginStatus(
  plugin: MemberPlugin,
  hasSkillIssues = false
): PluginStatus {
  switch (plugin.connection.kind) {
    case "connected":
      return hasSkillIssues ? "issues" : "active";
    case "oauth":
    case "credentials":
      return "issues";
    default:
      return "inactive";
  }
}
