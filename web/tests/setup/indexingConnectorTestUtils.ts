import {
  ConnectorCredentialPairStatus,
  type IndexingConnectorRow,
  type IndexingConnectorsResponse,
} from "@/lib/connectors/types";
import { ValidSources } from "@/lib/connectors/types/source";

/** A failed public Gmail pair with no runs, open errors or queue place. */
export function makeConnectorRow(
  overrides: Partial<IndexingConnectorRow> = {}
): IndexingConnectorRow {
  return {
    cc_pair_id: 1,
    name: "Sales Mailbox",
    source: ValidSources.Gmail,
    access_type: "public",
    cc_pair_status: ConnectorCredentialPairStatus.ACTIVE,
    status: "failed",
    creator_email: null,
    creator_name: null,
    docs_indexed: 12,
    last_success: null,
    latest_index_attempt: null,
    open_error_count: 0,
    group_count: 0,
    group_names: [],
    queue_position: null,
    permissions: { operate: true },
    ...overrides,
  };
}

/** One page of the status list holding `items`, its counts taken from them. */
export function makeConnectorsPage(
  items: IndexingConnectorRow[]
): IndexingConnectorsResponse {
  const statusCounts: IndexingConnectorsResponse["status_counts"] = {
    indexing: 0,
    syncing: 0,
    failed: 0,
    deleting: 0,
    scheduled: 0,
    indexed: 0,
    paused: 0,
  };
  const sourceCounts: IndexingConnectorsResponse["source_counts"] = {};
  for (const row of items) {
    statusCounts[row.status] += 1;
    sourceCounts[row.source] = (sourceCounts[row.source] ?? 0) + 1;
  }
  return {
    items,
    total_items: items.length,
    status_counts: statusCounts,
    source_counts: sourceCounts,
    federated_connectors: [],
  };
}
