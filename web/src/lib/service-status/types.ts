/** Mirrors `ClusterStatus` in backend/onyx/document_index/opensearch/models.py. */

export type ClusterHealth = "green" | "yellow" | "red";

export type ClusterIssueKind =
  | "cluster_red"
  | "unassigned_shards"
  | "disk"
  | "vector_memory"
  | "jvm_memory"
  | "index_missing"
  | "nodes_unanswered";

export type ClusterIssueSeverity = "critical" | "warning";

export type VectorQuantization = "none" | "scalar_7_bit" | "scalar_1_bit";

export interface ClusterIssue {
  kind: ClusterIssueKind;
  severity: ClusterIssueSeverity;
  node_names: string[];
  // The highest usage percent among node_names, or the count of unassigned
  // shards or unanswered nodes.
  value: number;
}

export interface ClusterNodeStatus {
  node_id: string;
  name: string;
  shard_count: number;
  memory_bytes: number;
  file_cache_bytes: number;
  vector_bytes: number;
  heap_max_bytes: number;
  heap_used_bytes: number;
  disk_total_bytes: number;
  disk_used_bytes: number;
  cpu_percent: number;
  load_average_1m: number | null;
  search_queue: number;
  search_rejected: number;
}

export interface ClusterIndexStatus {
  index_name: string;
  is_current: boolean;
  model_name: string;
  model_dim: number;
  vector_quantization: VectorQuantization;
  health: string | null;
  chunk_count: number;
  deleted_chunk_count: number;
  store_size_bytes: number;
  primary_shards: number;
  replicas: number;
}

/** The usage percents at which a data node gets a warning or critical issue. */
export interface UsageThresholds {
  disk_warning_percent: number;
  disk_critical_percent: number;
  vector_warning_percent: number;
  vector_critical_percent: number;
}

export interface ClusterStatus {
  checked_at: string;
  version: string | null;
  health: ClusterHealth;
  data_node_count: number;
  primary_shards: number;
  active_shards: number;
  unassigned_shards: number;
  nodes: ClusterNodeStatus[];
  indexes: ClusterIndexStatus[];
  issues: ClusterIssue[];
  thresholds: UsageThresholds;
}

/** Mirrors `SearchActivity` in backend/onyx/document_index/opensearch/search_samples.py. */

export type SearchResult = "ok" | "error" | "timeout";

export interface SearchSample {
  at_ms: number;
  client_ms: number;
  server_ms: number | null;
  search_type: string;
  result: SearchResult;
}

export interface SearchRatePoint {
  minute_ms: number;
  // 60, or the seconds elapsed so far for the current minute.
  seconds: number;
  count: number;
  error_count: number;
  // Percentiles of the minute's successful searches; null without any.
  p10_ms: number | null;
  p90_ms: number | null;
}

export interface SearchActivity {
  window_minutes: number;
  total_count: number;
  error_count: number;
  p90_ms: number | null;
  rate: SearchRatePoint[];
  // A minute whose p90 is above this shows as slow.
  slow_p90_ms: number;
  // Every slow or failed search, and a random few of each minute's others.
  samples: SearchSample[];
  sampled: boolean;
}
