import { SvgJira, SvgLinear, SvgNotion, SvgSentry } from "@opal/logos";
import type { IconFunctionComponent } from "@opal/types";

export interface SuggestedMCPPlugin {
  id: "linear" | "notion" | "sentry" | "atlassian";
  name: string;
  serverUrl: string;
  docsUrl: string;
  icon: IconFunctionComponent;
}

export const SUGGESTED_MCP_PLUGINS: readonly SuggestedMCPPlugin[] = [
  {
    id: "linear",
    name: "Linear",
    serverUrl: "https://mcp.linear.app/mcp",
    docsUrl: "https://linear.app/docs/mcp",
    icon: SvgLinear,
  },
  {
    id: "notion",
    name: "Notion",
    serverUrl: "https://mcp.notion.com/mcp",
    docsUrl: "https://developers.notion.com/guides/mcp/get-started-with-mcp",
    icon: SvgNotion,
  },
  {
    id: "sentry",
    name: "Sentry",
    serverUrl: "https://mcp.sentry.dev/mcp",
    docsUrl: "https://mcp.sentry.dev/",
    icon: SvgSentry,
  },
  {
    id: "atlassian",
    name: "Atlassian",
    serverUrl: "https://mcp.atlassian.com/v2/mcp",
    docsUrl:
      "https://support.atlassian.com/atlassian-ai-gateway/docs/get-started-with-the-atlassian-remote-mcp-server/",
    icon: SvgJira,
  },
];

/** True when a suggested MCP server covers the service of a preset, matched
 * on the service key (`LINEAR` and `linear`). The catalog then shows only the
 * server: it needs no OAuth app of the admin's own. */
export function hasSuggestedMcpServer(presetId: string): boolean {
  const service = presetId.toLowerCase();
  return SUGGESTED_MCP_PLUGINS.some((server) => server.id === service);
}
