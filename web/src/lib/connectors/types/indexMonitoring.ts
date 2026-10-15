import type {
  CCPairThroughputResponse,
  ConnectorCredentialPairStatus,
} from "@/lib/connectors/types/ccPair";
import type { ValidSources } from "@/lib/connectors/types/source";
import type { PermissionsOf } from "@/lib/permissions/resource-actions";
import type {
  AccessType,
  FederatedConnectorStatus,
  IndexAttemptSnapshot,
} from "@/lib/types";

/** Mirrors `IndexingOverviewResponse`: the readable pairs at a glance, plus their throughput over the window. */
export interface IndexingOverviewResponse {
  indexing_connectors: number;
  active_connectors: number;
  /** Documents indexed inside the window. */
  recent_docs_indexed: number;
  total_docs_indexed: number;
  throughput: CCPairThroughputResponse;
}

/** Mirrors `IndexingConnectorStatus`: the status page's buckets, in list order. */
export const INDEXING_CONNECTOR_STATUSES = [
  "indexing",
  "failed",
  "paused",
  "scheduled",
  "indexed",
] as const;
export type IndexingConnectorStatus =
  (typeof INDEXING_CONNECTOR_STATUSES)[number];

/** Mirrors `IndexingConnectorRow`: one pair in the status page's list, with its latest index attempt. */
export interface IndexingConnectorRow {
  cc_pair_id: number;
  name: string;
  source: ValidSources;
  access_type: AccessType;
  /** The pair's own state, which names the tag for a pair that is deleting, invalid or on its first index. */
  cc_pair_status: ConnectorCredentialPairStatus;
  status: IndexingConnectorStatus;
  creator_email: string | null;
  docs_indexed: number;
  last_success: string | null;
  latest_index_attempt: IndexAttemptSnapshot | null;
  /** Place in the line of queued index attempts, from 1, while the latest waits. */
  queue_position: number | null;
  permissions: PermissionsOf<"CCPair">;
}

/** Mirrors `IndexingConnectorsResponse`. `status_counts` ignores the status filter. */
export interface IndexingConnectorsResponse {
  items: IndexingConnectorRow[];
  total_items: number;
  status_counts: Record<IndexingConnectorStatus, number>;
  /** Admins only, on the first page with no status filter. */
  federated_connectors: FederatedConnectorStatus[];
}

/** The list's query, as the connectors route takes it. */
export interface IndexingConnectorsQuery {
  pageNum: number;
  pageSize: number;
  /** Matched against the name. */
  q: string;
  status: IndexingConnectorStatus | null;
}
