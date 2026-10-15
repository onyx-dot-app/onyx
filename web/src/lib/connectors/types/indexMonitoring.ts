import type { CCPairThroughputResponse } from "@/lib/connectors/types/ccPair";

/** Mirrors `IndexingOverviewResponse`: the readable pairs at a glance, plus their throughput over the window. */
export interface IndexingOverviewResponse {
  indexing_connectors: number;
  active_connectors: number;
  /** Documents indexed inside the window. */
  recent_docs_indexed: number;
  total_docs_indexed: number;
  throughput: CCPairThroughputResponse;
}
