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
 * of another shape, and the picker must not take the composer down with it. Reported rather than
 * dropped in silence — an emptied picker is indistinguishable from a workspace with no connectors.
 * The shape only, never the body: it names the workspace's connectors, which is why the response is
 * kept out of persisted storage to begin with.
 */
function sourcesOf(data: unknown, endpoint: string): DocumentSource[] {
  // `undefined` is the query before it resolves, not a bad answer.
  if (data === undefined) return NO_SOURCES;
  if (!Array.isArray(data)) {
    console.warn(
      `Ignoring ${endpoint} response: expected an array, got ${data === null ? "null" : typeof data}`,
    );
    return NO_SOURCES;
  }
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
  const { settings, isPending: settingsPending } = useWorkspaceSettings();
  /*
   * Held until the setting is known: the whole `/manage` router answers 501 without a vector DB
   * (connector.py's router dependency), and the retry doubles it, so guessing costs every such
   * deployment two failed requests per launch. Only the *pending* case waits — if `/settings`
   * fails outright the optimistic default still applies, or one settings outage would leave the
   * picker empty everywhere.
   */
  const indexedEnabled =
    serverUrl !== null && settings.vector_db_enabled && !settingsPending;

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
    () => [
      ...sourcesOf(indexed.data, "/manage/connector-status"),
      ...sourcesOf(federated.data, "/federated"),
    ],
    [indexed.data, federated.data],
  );

  return {
    sources,
    isLoading:
      (indexedEnabled && indexed.isLoading) ||
      (serverUrl !== null && federated.isLoading),
  };
}
