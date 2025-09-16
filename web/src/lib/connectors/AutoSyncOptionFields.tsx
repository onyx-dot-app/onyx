import { ValidAutoSyncSource } from "@/lib/types";
import { JSX } from "react";

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
  gmail: {},
};
