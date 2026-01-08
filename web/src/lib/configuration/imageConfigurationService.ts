/**
 * Image Generation Configuration Service
 * API functions for managing image generation configurations
 */

// Types
export interface ImageGenerationConfigView {
  image_provider_id: string; // Primary key
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
  imageProviderId: string;
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
 *
 * Two modes:
 * 1. Direct: provider + apiKey provided
 * 2. From existing provider: sourceLlmProviderId provided (backend fetches API key)
 */
export async function testImageGenerationApiKey(
  modelName: string,
  options: {
    // Option 1: Direct API key
    provider?: string;
    apiKey?: string;
    // Option 2: Use existing provider
    sourceLlmProviderId?: number;
    // Additional fields
    apiBase?: string;
    apiVersion?: string;
    deploymentName?: string;
  }
): Promise<TestApiKeyResult> {
  try {
    const response = await fetch(IMAGE_GEN_TEST_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model_name: modelName,
        provider: options.provider || null,
        api_key: options.apiKey || null,
        source_llm_provider_id: options.sourceLlmProviderId || null,
        api_base: options.apiBase || null,
        api_version: options.apiVersion || null,
        deployment_name: options.deploymentName || null,
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
  imageProviderId: string
): Promise<ImageGenerationCredentials> {
  const response = await fetch(
    `${IMAGE_GEN_CONFIG_URL}/${imageProviderId}/credentials`
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
      image_provider_id: options.imageProviderId,
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

  // If true, apiKey was changed by user; if false, backend preserves existing key
  apiKeyChanged?: boolean;
}

/**
 * Update image generation configuration
 * Backend deletes old LLM provider and creates new one
 */
export async function updateImageGenerationConfig(
  imageProviderId: string,
  options: ImageGenerationConfigUpdateOptions
): Promise<ImageGenerationConfigView> {
  const response = await fetch(`${IMAGE_GEN_CONFIG_URL}/${imageProviderId}`, {
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
      // If false, backend preserves existing API key
      api_key_changed: options.apiKeyChanged ?? false,
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
  imageProviderId: string
): Promise<void> {
  const response = await fetch(
    `${IMAGE_GEN_CONFIG_URL}/${imageProviderId}/default`,
    {
      method: "POST",
    }
  );

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Failed to set default");
  }
}

/**
 * Unset image generation config as default
 */
export async function unsetDefaultImageGenerationConfig(
  imageProviderId: string
): Promise<void> {
  const response = await fetch(
    `${IMAGE_GEN_CONFIG_URL}/${imageProviderId}/default`,
    {
      method: "DELETE",
    }
  );

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Failed to unset default");
  }
}

/**
 * Delete image generation configuration
 */
export async function deleteImageGenerationConfig(
  imageProviderId: string
): Promise<void> {
  const response = await fetch(`${IMAGE_GEN_CONFIG_URL}/${imageProviderId}`, {
    method: "DELETE",
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Failed to delete config");
  }
}
