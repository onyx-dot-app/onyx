import type { CCPairFullInfo } from "@/lib/connectors/types";
import { normalizeSeafileConnectorConfig } from "@/lib/connectors/seafile/seafileConfig";
import type { SeafileConnectorConfig } from "@/lib/connectors/seafile/seafileConfig";

export async function updateSeafileConnectorConfig(
  ccPair: CCPairFullInfo,
  config: SeafileConnectorConfig
): Promise<void> {
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
      }),
    }
  );

  if (!response.ok) {
    const error = await response.json().catch(() => null);
    throw new Error(error?.detail || "Failed to update Seafile settings");
  }
}
