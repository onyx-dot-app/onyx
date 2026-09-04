import type { ConnectorStatus } from "@/lib/types";
import { SWR_KEYS } from "@/lib/swr-keys";

import type { CCPairFullInfo } from "./types";
import { normalizeSeafileConnectorConfig } from "./seafileConfig";
import type { SeafileConnectorConfig } from "./seafileConfig";

async function fetchCurrentGroupIds(ccPairId: number): Promise<number[]> {
  const response = await fetch(SWR_KEYS.adminConnectorStatus);
  if (!response.ok) {
    throw new Error(await response.text());
  }

  const statuses = (await response.json()) as ConnectorStatus<any, any>[];
  return (
    statuses.find((status) => status.cc_pair_id === ccPairId)?.groups ?? []
  );
}

export async function updateSeafileConnectorConfig(
  ccPair: CCPairFullInfo,
  config: SeafileConnectorConfig
): Promise<void> {
  const groups = await fetchCurrentGroupIds(ccPair.id);
  const response = await fetch(
    `/api/manage/admin/connector/${ccPair.connector.id}`,
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        name: ccPair.connector.name,
        source: ccPair.connector.source,
        input_type: ccPair.connector.input_type,
        connector_specific_config: normalizeSeafileConnectorConfig(config),
        refresh_freq: ccPair.connector.refresh_freq,
        prune_freq: ccPair.connector.prune_freq,
        indexing_start: ccPair.connector.indexing_start,
        access_type: ccPair.access_type,
        groups,
      }),
    }
  );

  if (!response.ok) {
    const error = await response.json().catch(() => null);
    throw new Error(error?.detail || "Failed to update Seafile settings");
  }
}
