import type { ValidAutoSyncSource } from "@/lib/connectors/types/source";

interface AutoSyncConfig {
  notice?: string;
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
  jira_service_management: {},
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
};
