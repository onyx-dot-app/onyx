import type { ErrorResponseBody } from "@/lib/fetcher";
import type { ImageGenerationConfigView } from "@/lib/imageGeneration/types";

const CONFIG_URL = "/api/admin/image-generation/config";

async function throwOnError(response: Response, fallback: string) {
  if (response.ok) return;
  const error: ErrorResponseBody = await response.json().catch(() => ({}));
  throw new Error(error.detail || fallback);
}

/** Uses a model of a connected LLM provider, with that provider's credentials. */
export async function linkImageGenerationModel(
  llmProviderId: number,
  modelName: string,
  isDefault: boolean,
  customDisplayName?: string | null
): Promise<ImageGenerationConfigView> {
  const response = await fetch(`${CONFIG_URL}/link`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      llm_provider_id: llmProviderId,
      model_name: modelName,
      is_default: isDefault,
      custom_display_name: customDisplayName ?? null,
    }),
  });
  await throwOnError(response, "Failed to connect model");
  return response.json();
}

/** Renames a connected image model; null restores its catalog name. */
export async function renameImageGenerationConfig(
  imageProviderId: string,
  customDisplayName: string | null
): Promise<void> {
  const response = await fetch(`${CONFIG_URL}/${imageProviderId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ custom_display_name: customDisplayName }),
  });
  await throwOnError(response, "Failed to rename model");
}

export async function setDefaultImageGenerationConfig(
  imageProviderId: string
): Promise<void> {
  const response = await fetch(`${CONFIG_URL}/${imageProviderId}/default`, {
    method: "POST",
  });
  await throwOnError(response, "Failed to set default");
}

export async function unsetDefaultImageGenerationConfig(
  imageProviderId: string
): Promise<void> {
  const response = await fetch(`${CONFIG_URL}/${imageProviderId}/default`, {
    method: "DELETE",
  });
  await throwOnError(response, "Failed to unset default");
}

/** Disconnects a model. A config with its own credentials also deletes them. */
export async function deleteImageGenerationConfig(
  imageProviderId: string
): Promise<void> {
  const response = await fetch(`${CONFIG_URL}/${imageProviderId}`, {
    method: "DELETE",
  });
  await throwOnError(response, "Failed to disconnect model");
}
