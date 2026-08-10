import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  getConnectorSources,
  getFederatedSources,
} from "@/api/chat/connectors";
import { QUERY_KEYS } from "@/api/query-keys";
import { useWorkspaceSettings } from "@/api/settings";
import type { DocumentSource } from "@/chat/sources";
import { useSession } from "@/state/session";

const NO_SOURCES: DocumentSource[] = [];

/*
 * Array-checked, not just null-checked: a proxy error page or auth redirect answers 200 with a body
 * of another shape, and the picker must not take the composer down with it.
 */
function sourcesOf(data: unknown): DocumentSource[] {
  if (!Array.isArray(data)) return NO_SOURCES;
  return data
    .map((row: { source?: unknown }) => row?.source)
    .filter((source): source is DocumentSource => typeof source === "string");
}

export interface ConnectorSources {
  sources: DocumentSource[];
  isLoading: boolean;
}

export function useConnectorSources(): ConnectorSources {
  const serverUrl = useSession((state) => state.serverUrl);
  const { settings } = useWorkspaceSettings();
  const indexedEnabled = serverUrl !== null && settings.vector_db_enabled;

  const indexed = useQuery({
    queryKey: QUERY_KEYS.connectorSources(serverUrl),
    enabled: indexedEnabled,
    queryFn: ({ signal }) => getConnectorSources(signal),
  });

  // Not gated on the vector DB — a federated connector is queried live, indexed or not.
  const federated = useQuery({
    queryKey: QUERY_KEYS.federatedSources(serverUrl),
    enabled: serverUrl !== null,
    queryFn: ({ signal }) => getFederatedSources(signal),
  });

  const sources = useMemo(
    () => [...sourcesOf(indexed.data), ...sourcesOf(federated.data)],
    [indexed.data, federated.data],
  );

  return {
    sources,
    isLoading:
      (indexedEnabled && indexed.isLoading) ||
      (serverUrl !== null && federated.isLoading),
  };
}
