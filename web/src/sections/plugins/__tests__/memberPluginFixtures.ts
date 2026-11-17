import type { ToolSnapshot } from "@/lib/tools/types";

export function memberTool(
  overrides: Partial<ToolSnapshot> = {}
): ToolSnapshot {
  return {
    id: 7,
    name: "Reports API",
    display_name: "Reports API",
    description: "Read weekly reports and project summaries.",
    definition: {},
    custom_headers: [],
    in_code_tool_id: null,
    passthrough_auth: false,
    enabled: true,
    chat_selectable: true,
    agent_creation_selectable: true,
    default_enabled: false,
    default_chat_enabled: true,
    permissions: {},
    ...overrides,
  };
}

export const storedMcpTool = memberTool({
  id: 71,
  name: "search_issues",
  display_name: "Search issues",
  description: "Find issues in the projects you can access.",
  definition: null,
  mcp_server_id: 7,
});
