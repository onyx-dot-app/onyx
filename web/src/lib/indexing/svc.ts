import {
  AdvancedSearchConfiguration,
  CloudEmbeddingProvider,
  EmbeddingProvider,
  HostedEmbeddingModel,
  RerankingDetails,
  SavedSearchSettings,
  SwitchoverType,
} from "@/interfaces/indexing";

export async function deleteSearchSettings(search_settings_id: number) {
  return await fetch(`/api/search-settings/delete-search-settings`, {
    method: "DELETE",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ search_settings_id }),
  });
}

interface TestEmbeddingArgs {
  provider_type: string;
  modelName: string;
  apiKey: string | null;
  apiUrl: string | null;
  apiVersion: string | null;
  deploymentName: string | null;
}

export async function testEmbedding({
  provider_type,
  modelName,
  apiKey,
  apiUrl,
  apiVersion,
  deploymentName,
}: TestEmbeddingArgs) {
  const testModelName =
    provider_type === "openai" ? "text-embedding-3-small" : modelName;

  return await fetch("/api/admin/embedding/test-embedding", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      provider_type: provider_type,
      api_key: apiKey,
      api_url: apiUrl,
      model_name: testModelName,
      api_version: apiVersion,
      deployment_name: deploymentName,
    }),
  });
}

export async function updateSearchSettings(
  searchSettings: SavedSearchSettings
) {
  return await fetch("/api/search-settings/update-inference-settings", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      ...searchSettings,
    }),
  });
}

// We use a spread operation to merge properties from multiple objects into a single object.
// Advanced embedding details may update default values.
// Do NOT modify the order unless you are positive the new hierarchy is correct.
export function combineSearchSettings(
  selectedProvider: CloudEmbeddingProvider | HostedEmbeddingModel,
  advancedEmbeddingDetails: AdvancedSearchConfiguration,
  rerankingDetails: RerankingDetails,
  provider_type: EmbeddingProvider | null,
  switchover_type?: SwitchoverType
): SavedSearchSettings {
  return {
    ...selectedProvider,
    ...advancedEmbeddingDetails,
    ...rerankingDetails,
    provider_type: provider_type,
    switchover_type,
  };
}
