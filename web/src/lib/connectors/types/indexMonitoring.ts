import type {
  CCPairRun,
  CCPairRunStatusGroup,
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
  /** An estimate of the documents the window's runs processed, each time a run processed one. */
  recent_docs_indexed: number;
  /** The sum of each pair's documents, so a document two pairs hold counts twice. */
  total_docs_indexed: number;
  /** Optional: a backend that does not report it leaves Paused off the status page. */
  paused_connectors?: number;
  throughput: CCPairThroughputResponse;
}

/** Mirrors `IndexingConnectorStatus`: the status page's buckets, in the rank order the API sorts rows by. */
export const INDEXING_CONNECTOR_STATUSES = [
  "indexing",
  "syncing",
  "failed",
  "deleting",
  "scheduled",
  "indexed",
  "paused",
] as const;
export type IndexingConnectorStatus =
  (typeof INDEXING_CONNECTOR_STATUSES)[number];

/** Mirrors `IndexingConnectorRow`: one pair in the status page's list, with its latest index attempt. */
export interface IndexingConnectorRow {
  cc_pair_id: number;
  name: string;
  source: ValidSources;
  access_type: AccessType;
  /** The pair's own state, which names the tag for a pair that is invalid or on its first index. */
  cc_pair_status: ConnectorCredentialPairStatus;
  status: IndexingConnectorStatus;
  creator_email: string | null;
  /** The owner's display name, unset when the owner has none. */
  creator_name: string | null;
  docs_indexed: number;
  last_success: string | null;
  latest_index_attempt: IndexAttemptSnapshot | null;
  /** The latest attempt's open errors, whole entities included, plus the pair's open prune and check runs. */
  open_error_count: number;
  /** The groups that read a private pair's documents and the viewer can see, so a scoped viewer can get 0. */
  group_count: number;
  /** Those groups' names, sorted. Set for private and restricted-sync pairs only. */
  group_names: string[];
  /** Place in the line of queued index attempts, from 1, while the latest waits. */
  queue_position: number | null;
  permissions: PermissionsOf<"CCPair">;
}

/** Mirrors `IndexingConnectorsResponse`. `status_counts` ignores the status filter. */
export interface IndexingConnectorsResponse {
  items: IndexingConnectorRow[];
  total_items: number;
  status_counts: Record<IndexingConnectorStatus, number>;
  /** Matching pairs per source over every page, so a divider's count covers rows on other pages. */
  source_counts: Partial<Record<ValidSources, number>>;
  /** Admins only, on the first page with no status filter. */
  federated_connectors: FederatedConnectorStatus[];
}

/** The list's query, as the connectors route takes it. */
export interface IndexingConnectorsQuery {
  pageNum: number;
  pageSize: number;
  /** Matched against the name. */
  q: string;
  /** Pairs in any of these buckets, or every pair when null. */
  status: readonly IndexingConnectorStatus[] | null;
}

/** Mirrors `CCPairRef`: a pair named in a fleet-wide feed. */
export interface CCPairRef {
  id: number;
  name: string;
  source: ValidSources;
  /** The viewer may re-fetch single documents of this pair. */
  can_resolve: boolean;
  /** The viewer may mark this pair's runs resolved. */
  can_resolve_runs: boolean;
}

/** Mirrors `IndexingRun`: one run in the fleet-wide feed, with the pair it ran on. */
export interface IndexingRun {
  cc_pair: CCPairRef;
  run: CCPairRun;
}

/** Mirrors `IndexingRunsResponse`. `status_counts` ignores the status filter. */
export interface IndexingRunsResponse {
  items: IndexingRun[];
  total_items: number;
  status_counts: Record<CCPairRunStatusGroup, number>;
}
