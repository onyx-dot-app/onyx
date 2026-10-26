import {
  SvgAsana,
  SvgHubSpot,
  SvgJira,
  SvgLinear,
  SvgNotion,
  SvgSentry,
  SvgSlack,
} from "@opal/logos";
import type { IconFunctionComponent } from "@opal/types";

export interface SuggestedMCPPlugin {
  id:
    | "linear"
    | "notion"
    | "sentry"
    | "atlassian"
    | "slack"
    | "hubspot"
    | "asana";
  name: string;
  serverUrl: string;
  docsUrl: string;
  icon: IconFunctionComponent;
}

export const SUGGESTED_MCP_PLUGINS: readonly SuggestedMCPPlugin[] = [
  {
    id: "slack",
    name: "Slack",
    serverUrl: "https://mcp.slack.com/mcp",
    docsUrl: "https://docs.slack.dev/ai/slack-mcp-server/",
    icon: SvgSlack,
  },
  {
    id: "hubspot",
    name: "HubSpot",
    serverUrl: "https://mcp.hubspot.com",
    docsUrl:
      "https://developers.hubspot.com/docs/apps/developer-platform/build-apps/integrate-with-the-remote-hubspot-mcp-server",
    icon: SvgHubSpot,
  },
  {
    id: "asana",
    name: "Asana",
    serverUrl: "https://mcp.asana.com/v2/mcp",
    docsUrl:
      "https://developers.asana.com/docs/connecting-mcp-clients-to-asanas-v2-server",
    icon: SvgAsana,
  },
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
