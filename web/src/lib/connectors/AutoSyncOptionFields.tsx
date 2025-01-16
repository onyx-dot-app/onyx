import { ValidAutoSyncSource } from "@/lib/types";

// The first key is the connector type, and the second key is the field name
export const autoSyncConfigBySource: Record<
  ValidAutoSyncSource,
  Record<
    string,
    {
      label: string;
      subtext: JSX.Element;
    }
  >
> = {
  confluence: {},
  google_drive: {},
  gmail: {},
  slack: {},
  salesforce: {},
};
