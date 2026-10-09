import type { CCPairFullInfo } from "@/lib/connectors/types";
import type { AccessType } from "@/lib/types";

/** The pair that the connector form edits, as the page loaded it. */
export interface ConnectorEditTarget {
  ccPair: CCPairFullInfo;
  /** The pair's data-access groups that the user can see. */
  dataAccessGroupIds: number[];
}

/**
 * The full proposed state of a pair. Mirrors `ConnectorEditProposal` in
 * `backend/onyx/server/documents/connector_edit.py`.
 */
export interface ConnectorEditProposal {
  connector_specific_config: Record<string, unknown>;
  access_type: AccessType;
  data_access_group_ids: number[];
  credential_id: number;
  indexing_start: string | null;
  name: string;
  refresh_freq: number | null;
  prune_freq: number | null;
}
