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
  zoom: {
    notice:
      "Zoom keeps a session's participant list for about 15 months. After " +
      "that, Onyx cannot tell who attended. Rather than give the transcript " +
      "wider access than the session had, Onyx reports the session as an " +
      "indexing error. So while Auto Sync is on, sessions older than that " +
      "window stay out of search.",
  },
};
