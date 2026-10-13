import type { CCPairFullInfo } from "@/lib/connectors/types";

/** The pair that the connector form edits, as the page loaded it. */
export interface ConnectorEditTarget {
  ccPair: CCPairFullInfo;
}
