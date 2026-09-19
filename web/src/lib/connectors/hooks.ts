"use client";

import { useMemo } from "react";
import { useFederatedConnectors } from "@/lib/hooks";
import { useSettings } from "@/lib/settings/hooks";
import useCCPairs from "@/hooks/useCCPairs";
import { ValidSources } from "@/lib/types";

/**
 * The source types this workspace has connected — indexed connectors first,
 * then federated ones.
 *
 * Reads `vectorDbEnabled` itself, so callers do not thread it. With the vector
 * DB off, `useCCPairs` skips its fetch and the list is federated-only.
 *
 * The array is deliberately neither deduplicated nor sorted. Callers that
 * want one entry per source type run the result through
 * `getConfiguredSources`, which dedups on the cleaned name.
 *
 * `error` is set when either request failed, so the list is short rather than
 * genuinely empty. A caller that hides controls on an empty list should check
 * it, otherwise a failed fetch is indistinguishable from a workspace with
 * nothing connected.
 */
export function useAvailableSources(): {
  availableSources: ValidSources[];
  isLoading: boolean;
  /**
   * Whether the roster is complete: every constituent fetch holds a
   * snapshot, stale allowed. A nonempty array is no proof of this — one
   * constituent can fail its first load while the other returns — so
   * callers resolving a selection must gate on this, not on length.
   */
  settled: boolean;
  error: unknown;
} {
  // `vectorDbEnabled` reads false while settings load, which would make
  // `useCCPairs` skip its fetch and report ready. Wait for settings first, or
  // a cached federated list alone would look like the complete set.
  const { vectorDbEnabled, isLoading: settingsLoading } = useSettings();
  const {
    ccPairs,
    isLoading: ccPairsLoading,
    hasLoaded: ccPairsHasLoaded,
    error: ccPairsError,
  } = useCCPairs(vectorDbEnabled);
  const {
    data: federatedConnectors,
    isLoading: federatedLoading,
    error: federatedError,
  } = useFederatedConnectors();

  const availableSources = useMemo(
    () => [
      ...ccPairs.map((ccPair) => ccPair.source),
      ...(federatedConnectors?.map((connector) => connector.source) ?? []),
    ],
    [ccPairs, federatedConnectors]
  );

  return {
    availableSources,
    isLoading: settingsLoading || ccPairsLoading || federatedLoading,
    settled:
      !settingsLoading && ccPairsHasLoaded && federatedConnectors !== undefined,
    error: ccPairsError ?? federatedError,
  };
}
