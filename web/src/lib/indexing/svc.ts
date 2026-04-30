import type { Settings } from "@/interfaces/settings";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  EmbeddingModel,
  EmbeddingPrecision,
  EmbeddingProviderName,
  SwitchoverType,
} from "@/lib/indexing/interfaces";
import { isCloudBased } from "@/lib/indexing";

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

/**
 * Tests and saves embedding provider credentials.
 * Tests the connection first, then persists the credentials.
 * Throws on failure with a user-facing error message.
 */
export async function connectEmbeddingProvider({
  providerType,
  apiKey,
  apiUrl,
}: {
  providerType: string;
  apiKey: string;
  apiUrl: string;
}): Promise<void> {
  const testResponse = await testEmbedding({
    provider_type: providerType,
    modelName: "",
    apiKey,
    apiUrl,
    apiVersion: null,
    deploymentName: null,
  });

  if (!testResponse.ok) {
    const err = await testResponse.json();
    throw new Error(err.detail ?? "Embedding test failed");
  }

  const saveResponse = await fetch(SWR_KEYS.embeddingProviders, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      provider_type: providerType,
      api_key: apiKey,
      api_url: apiUrl,
      is_default_provider: false,
      is_configured: true,
    }),
  });

  if (!saveResponse.ok) {
    const err = await saveResponse.json();
    throw new Error(err.detail ?? "Failed to save provider");
  }
}

/**
 * Disconnects an embedding provider by deleting its credentials.
 * Throws on failure with a user-facing error message.
 */
export async function disconnectEmbeddingProvider(
  providerType: string
): Promise<void> {
  const response = await fetch(
    `${SWR_KEYS.embeddingProviders}/${providerType}`,
    { method: "DELETE" }
  );

  if (!response.ok) {
    const err = await response.json();
    throw new Error(err.detail ?? "Failed to disconnect provider");
  }
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

/**
 * Cancels an in-flight embedding-model switchover. Marks the FUTURE search
 * settings row as PAST, expires its index attempts, and drops the secondary
 * vector index.
 */
export async function cancelNewEmbedding(): Promise<Response> {
  return await fetch("/api/search-settings/cancel-new-embedding", {
    method: "POST",
  });
}

interface SetNewSearchSettingsArgs {
  model: EmbeddingModel;
  providerName: EmbeddingProviderName;
  switchoverType: SwitchoverType;
  enableContextualRag: boolean;
  contextualRagLlmName: string | null;
  contextualRagLlmProvider: string | null;
}

export async function setNewSearchSettings({
  model,
  providerName,
  switchoverType,
  enableContextualRag,
  contextualRagLlmName,
  contextualRagLlmProvider,
}: SetNewSearchSettingsArgs): Promise<Response> {
  // The backend's EmbeddingProvider enum only contains cloud providers
  // (openai/cohere/voyage/google/litellm/azure). Self-hosted models live
  // under the frontend's EmbeddingProviderName for UI grouping (icon,
  // docs link), but the backend expects provider_type=null for them.
  const providerType = isCloudBased(providerName) ? providerName : null;

  return await fetch("/api/search-settings/set-new-search-settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model_name: model.modelName,
      model_dim: model.modelDim,
      normalize: model.normalize,
      query_prefix: model.queryPrefix,
      passage_prefix: model.passagePrefix,
      provider_type: providerType,
      api_key: null,
      api_url: null,
      index_name: null,
      multipass_indexing: false,
      embedding_precision: EmbeddingPrecision.FLOAT,
      enable_contextual_rag: enableContextualRag,
      contextual_rag_llm_name: contextualRagLlmName,
      contextual_rag_llm_provider: contextualRagLlmProvider,
      switchover_type: switchoverType,
    }),
  });
}
