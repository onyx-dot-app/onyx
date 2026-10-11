import type { ValidAutoSyncSource } from "@/lib/connectors/types/source";

/** A per-user MCP server the source's query-time censor fetches through. The
 * url's hostname must equal the censor's host constant so the card finds the
 * same server the censor will use. */
export interface PermSyncMcpServerConfig {
  name: string;
  url: string;
}

interface AutoSyncConfig {
  // Key under admin.connectorsList.settings.documentAccess.sync.sourceNotice.
  noticeKey?: "notion";
  mcpServer?: PermSyncMcpServerConfig;
  // Each key is posted as auto_sync_options.<key>, so it has to match the name
  // the backend reads.
  fields?: Record<
    string,
    {
      label: string;
      subtext: string;
    }
  >;
}

export const autoSyncConfigBySource: Record<
  ValidAutoSyncSource,
  AutoSyncConfig
> = {
  box: {},
  confluence: {},
  jira: {},
  google_drive: {},
  gmail: {},
  github: {},
  slack: {},
  salesforce: {},
  sharepoint: {},
  teams: {},
  outlook: {},
  canvas: {},
  onedrive: {},
  zoom: {},
  notion: {
    noticeKey: "notion",
    mcpServer: { name: "Notion MCP", url: "https://mcp.notion.com/mcp" },
  },
};
