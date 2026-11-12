import type { InstalledPlugin } from "@/lib/plugins/types";

export function workspaceAvailabilityLabel(
  plugin: InstalledPlugin,
  craftAvailable: boolean
): "enable" | "disable" | "manageAvailability" {
  const states =
    plugin.kind === "mcp"
      ? [
          plugin.server.default_chat_enabled,
          ...(craftAvailable ? [plugin.server.available_in_craft] : []),
        ]
      : [plugin.kind === "openapi" ? plugin.tool.enabled : plugin.app.enabled];
  if (states.every((enabled) => enabled === true)) return "disable";
  if (states.every((enabled) => enabled === false)) return "enable";
  return "manageAvailability";
}
