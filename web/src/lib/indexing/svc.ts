import type { Settings } from "@/interfaces/settings";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  EmbeddingModel,
  EmbeddingProviderName,
  SavedSearchSettings,
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
 *
 * `apiVersion` and `deploymentName` are Azure-specific — backend's
 * `CloudEmbeddingProviderCreationRequest` accepts them as optional, and
 * non-Azure providers should pass `null`.
 */
export async function connectEmbeddingProvider({
  providerType,
  apiKey,
  apiUrl,
  apiVersion,
  deploymentName,
}: {
  providerType: string;
  apiKey: string | null;
  apiUrl: string;
  apiVersion: string | null;
  deploymentName: string | null;
}): Promise<void> {
  if (apiKey !== null) {
    const testResponse = await testEmbedding({
      provider_type: providerType,
      modelName: "",
      apiKey,
      apiUrl,
      apiVersion,
      deploymentName,
    });

    if (!testResponse.ok) {
      const err = await testResponse.json();
      throw new Error(err.detail ?? "Embedding test failed");
    }
  }

  const body: Record<string, unknown> = {
    provider_type: providerType,
    api_url: apiUrl,
    api_version: apiVersion,
    deployment_name: deploymentName,
    is_default_provider: false,
    is_configured: true,
  };
  if (apiKey !== null) body.api_key = apiKey;

  const saveResponse = await fetch(SWR_KEYS.embeddingProviders, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
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
      enable_contextual_rag: enableContextualRag,
      contextual_rag_llm_name: contextualRagLlmName,
      contextual_rag_llm_provider: contextualRagLlmProvider,
      switchover_type: switchoverType,
    }),
  });
}

/**
 * Persists non-reindex search-settings updates (e.g. toggling Contextual RAG
 * or switching its LLM). Backend is `update_saved_search_settings` — it
 * mutates the CURRENT search-settings row in place rather than creating a new
 * one + kicking off a re-index. Caller is responsible for ensuring the
 * embedding-model fields in `settings` match the current model; the endpoint
 * does not validate this.
 */
export async function updateInferenceSettings(
  settings: SavedSearchSettings
): Promise<Response> {
  return await fetch("/api/search-settings/update-inference-settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  });
}
