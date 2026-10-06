import type { ManageAccessEntry } from "@/lib/connectors/accessType";
import type { ValidInputTypes } from "@/lib/types";
import type { ValidSources } from "@/lib/connectors/types/source";

export interface ConnectorBase<T> {
  name: string;
  source: ValidSources;
  input_type: ValidInputTypes;
  connector_specific_config: T;
  refresh_freq: number | null;
  prune_freq: number | null;
  indexing_start: Date | null;
  access_type: string;
  groups?: number[];
  /** Manage groups with roles; replaces `groups`. Placeholder-credential create only. */
  manage_access?: ManageAccessEntry[];
  /** A private connector's reader groups. Placeholder-credential create only. */
  data_access?: number[];
  from_beginning?: boolean;
}

export interface Connector<T> extends ConnectorBase<T> {
  id: number;
  credential_ids: number[];
  time_created: string;
  time_updated: string;
}

export interface ConnectorSnapshot {
  id: number;
  name: string;
  source: ValidSources;
  input_type: ValidInputTypes;
  // connector_specific_config
  refresh_freq: number | null;
  prune_freq: number | null;
  credential_ids: number[];
  indexing_start: number | null;
  time_created: string;
  time_updated: string;
  from_beginning?: boolean;
}
