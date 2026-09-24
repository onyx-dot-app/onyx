import type { ValidInputTypes, ValidSources } from "@/lib/types";

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
