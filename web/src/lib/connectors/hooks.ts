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
 * The array is deliberately neither deduplicated nor sorted. `useSourcePreferences`
 * keys off `availableSources.join(",")` to decide when the set has changed, so
 * reordering or collapsing entries would look like a different workspace and
 * reset the user's saved source selections. Callers that want one entry per
 * source type run the result through `getConfiguredSources`, which dedups on
 * the cleaned name.
 */
export function useAvailableSources(): {
  availableSources: ValidSources[];
  isLoading: boolean;
} {
  const { vectorDbEnabled } = useSettings();
  const { ccPairs, isLoading: ccPairsLoading } = useCCPairs(vectorDbEnabled);
  const { data: federatedConnectors, isLoading: federatedLoading } =
    useFederatedConnectors();

  const availableSources = useMemo(
    () => [
      ...ccPairs.map((ccPair) => ccPair.source),
      ...(federatedConnectors?.map((connector) => connector.source) ?? []),
    ],
    [ccPairs, federatedConnectors]
  );

  return {
    availableSources,
    isLoading: ccPairsLoading || federatedLoading,
  };
}
