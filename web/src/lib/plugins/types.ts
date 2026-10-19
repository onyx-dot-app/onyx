import type { MCPServer } from "@/lib/mcp/types";
import type { ToolSnapshot } from "@/lib/tools/types";
import type { ExternalAppAdminResponse } from "@/app/craft/v1/apps/registry";

export type InstalledPlugin =
  | { kind: "mcp"; server: MCPServer }
  | { kind: "openapi"; tool: ToolSnapshot }
  | { kind: "external-app"; app: ExternalAppAdminResponse };

export type PluginReference =
  | { kind: "mcp"; id: MCPServer["id"] }
  | { kind: "openapi"; id: ToolSnapshot["id"] }
  | { kind: "external-app"; id: ExternalAppAdminResponse["id"] };

export type ChatPluginReference = Exclude<
  PluginReference,
  { kind: "external-app" }
>;
