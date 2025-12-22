/**
 * Image Generation Configuration Service
 * API functions for managing image generation configurations
 */

// Types
export interface ImageGenerationConfigView {
  id: number;
  model_configuration_id: number;
  model_name: string;
  llm_provider_id: number;
  llm_provider_name: string;
  is_default: boolean;
}

export interface TestApiKeyResult {
  ok: boolean;
  errorMessage?: string;
}

export interface ImageGenerationCredentials {
  api_key: string | null;
  api_base: string | null;
  api_version: string | null;
  deployment_name: string | null;
}

// Creation options - either clone from existing provider or use new credentials
export interface ImageGenerationConfigCreateOptions {
  modelName: string;
  isDefault?: boolean;

  // Option 1: Clone mode - use credentials from existing provider
  sourceLlmProviderId?: number;

  // Option 2: New credentials mode
  provider?: string;
  apiKey?: string;
  apiBase?: string;
  apiVersion?: string;
  deploymentName?: string;
}

// API Endpoints
const IMAGE_GEN_CONFIG_URL = "/api/admin/image-generation/config";
const IMAGE_GEN_TEST_URL = "/api/admin/image-generation/test";

/**
 * Test API key for image generation provider
 */
export async function testImageGenerationApiKey(
  provider: string,
  apiKey: string,
  modelName: string,
  apiBase?: string,
  apiVersion?: string,
  deploymentName?: string
): Promise<TestApiKeyResult> {
  try {
    const response = await fetch(IMAGE_GEN_TEST_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        provider,
        api_key: apiKey,
        model_name: modelName,
        api_base: apiBase || null,
        api_version: apiVersion || null,
        deployment_name: deploymentName || null,
      }),
    });

    if (!response.ok) {
      const error = await response.json();
      return {
        ok: false,
        errorMessage: error.detail || "API key validation failed",
      };
    }

    return { ok: true };
  } catch (error) {
    return {
      ok: false,
      errorMessage:
        error instanceof Error ? error.message : "An error occurred",
    };
  }
}

/**
 * Fetch all image generation configurations
 */
export async function fetchImageGenerationConfigs(): Promise<
  ImageGenerationConfigView[]
> {
  const response = await fetch(IMAGE_GEN_CONFIG_URL);
  if (!response.ok) {
    throw new Error("Failed to fetch image generation configs");
  }
  return response.json();
}

/**
 * Fetch credentials for an image generation config (for edit mode)
 */
export async function fetchImageGenerationCredentials(
  configId: number
): Promise<ImageGenerationCredentials> {
  const response = await fetch(
    `${IMAGE_GEN_CONFIG_URL}/${configId}/credentials`
  );
  if (!response.ok) {
    throw new Error("Failed to fetch credentials");
  }
  return response.json();
}

/**
 * Create image generation configuration
 * Backend creates new LLM provider + model config + image config
 */
export async function createImageGenerationConfig(
  options: ImageGenerationConfigCreateOptions
): Promise<ImageGenerationConfigView> {
  const response = await fetch(IMAGE_GEN_CONFIG_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model_name: options.modelName,
      is_default: options.isDefault ?? false,
      // Clone mode
      source_llm_provider_id: options.sourceLlmProviderId,
      // New credentials mode
      provider: options.provider,
      api_key: options.apiKey,
      api_base: options.apiBase,
      api_version: options.apiVersion,
      deployment_name: options.deploymentName,
    }),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Failed to create config");
  }

  return response.json();
}

// Update options - same structure but without isDefault
export interface ImageGenerationConfigUpdateOptions {
  modelName: string;

  // Option 1: Clone mode - use credentials from existing provider
  sourceLlmProviderId?: number;

  // Option 2: New credentials mode
  provider?: string;
  apiKey?: string;
  apiBase?: string;
  apiVersion?: string;
  deploymentName?: string;
}

/**
 * Update image generation configuration
 * Backend deletes old LLM provider and creates new one
 */
export async function updateImageGenerationConfig(
  configId: number,
  options: ImageGenerationConfigUpdateOptions
): Promise<ImageGenerationConfigView> {
  const response = await fetch(`${IMAGE_GEN_CONFIG_URL}/${configId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model_name: options.modelName,
      // Clone mode
      source_llm_provider_id: options.sourceLlmProviderId,
      // New credentials mode
      provider: options.provider,
      api_key: options.apiKey,
      api_base: options.apiBase,
      api_version: options.apiVersion,
      deployment_name: options.deploymentName,
    }),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Failed to update config");
  }

  return response.json();
}

/**
 * Set image generation config as default
 */
export async function setDefaultImageGenerationConfig(
  configId: number
): Promise<void> {
  const response = await fetch(`${IMAGE_GEN_CONFIG_URL}/${configId}/default`, {
    method: "POST",
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Failed to set default");
  }
}

/**
 * Delete image generation configuration
 */
export async function deleteImageGenerationConfig(
  configId: number
): Promise<void> {
  const response = await fetch(`${IMAGE_GEN_CONFIG_URL}/${configId}`, {
    method: "DELETE",
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Failed to delete config");
  }
}
