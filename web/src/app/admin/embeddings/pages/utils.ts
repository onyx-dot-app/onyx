import {
  CloudEmbeddingProvider,
  HostedEmbeddingModel,
} from "@/components/embedding/interfaces";

import {
  AdvancedSearchConfiguration,
  SavedSearchSettings,
} from "../interfaces";

import { EmbeddingProvider } from "@/components/embedding/interfaces";
import { RerankingDetails } from "../interfaces";

export const deleteSearchSettings = async (search_settings_id: number) => {
  const response = await fetch(`/api/search-settings/delete-search-settings`, {
    method: "DELETE",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ search_settings_id }),
  });
  return response;
};

export const testEmbedding = async ({
  provider_type,
  modelName,
  apiKey,
  apiUrl,
  apiVersion,
  deploymentName,
}: {
  provider_type: string;
  modelName: string;
  apiKey: string | null;
  apiUrl: string | null;
  apiVersion: string | null;
  deploymentName: string | null;
}) => {
  const testModelName =
    provider_type === "openai" ? "text-embedding-3-small" : modelName;

  const testResponse = await fetch("/api/admin/embedding/test-embedding", {
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

  return testResponse;
};

// We use a spread operation to merge properties from multiple objects into a single object.
// Advanced embedding details may update default values.
// Do NOT modify the order unless you are positive the new hierarchy is correct.
export const combineSearchSettings = (
  selectedProvider: CloudEmbeddingProvider | HostedEmbeddingModel,
  advancedEmbeddingDetails: AdvancedSearchConfiguration,
  rerankingDetails: RerankingDetails,
  provider_type: EmbeddingProvider | null,
  background_reindex_enabled: boolean
): SavedSearchSettings => {
  return {
    ...selectedProvider,
    ...advancedEmbeddingDetails,
    ...rerankingDetails,
    provider_type: provider_type,
    background_reindex_enabled,
  };
};
