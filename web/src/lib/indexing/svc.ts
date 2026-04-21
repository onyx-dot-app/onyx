import type { Settings } from "@/interfaces/settings";
import {
  AdvancedSearchConfiguration,
  EmbeddingModelDescriptor,
  EmbeddingPrecision,
  EmbeddingProvider,
  RerankingDetails,
  SavedSearchSettings,
  SwitchoverType,
} from "@/lib/indexing/interfaces";

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

export async function saveAdminSettings(settings: Settings) {
  const response = await fetch("/api/admin/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  });

  if (!response.ok) {
    const errorMsg = (await response.json()).detail;
    throw new Error(errorMsg);
  }
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

/**
 * Cancels the FUTURE embedding model selection, reverting to just the
 * current (PRESENT) model.
 */
export async function cancelNewEmbedding(): Promise<Response> {
  return await fetch("/api/search-settings/cancel-new-embedding", {
    method: "POST",
  });
}

/**
 * Marks a model as the FUTURE embedding model. Does NOT start re-indexing —
 * that is a separate, explicit action.
 */
export async function setNewSearchSettings(
  model: EmbeddingModelDescriptor,
  switchoverType: SwitchoverType
): Promise<Response> {
  return await fetch("/api/search-settings/set-new-search-settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ...model,
      multipass_indexing: false,
      embedding_precision: EmbeddingPrecision.FLOAT,
      enable_contextual_rag: false,
      switchover_type: switchoverType,
    }),
  });
}

// We use a spread operation to merge properties from multiple objects into a single object.
// Advanced embedding details may update default values.
// Do NOT modify the order unless you are positive the new hierarchy is correct.
export function combineSearchSettings(
  selectedProvider: EmbeddingModelDescriptor,
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
