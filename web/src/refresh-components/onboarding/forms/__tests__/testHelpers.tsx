/**
 * Shared test helpers and mocks for onboarding form tests
 */
import React from "react";

// Mock Element.prototype.scrollIntoView for JSDOM (not implemented in jsdom)
Element.prototype.scrollIntoView = jest.fn();
import {
  WellKnownLLMProviderDescriptor,
  LLMProviderName,
  ModelConfiguration,
} from "@/app/admin/configuration/llm/interfaces";
import {
  OnboardingState,
  OnboardingActions,
  OnboardingStep,
} from "../../types";

/**
 * Creates a mock WellKnownLLMProviderDescriptor for testing
 */
export function createMockLLMDescriptor(
  name: string,
  modelConfigurations: ModelConfiguration[] = []
): WellKnownLLMProviderDescriptor {
  return {
    name,
    known_models:
      modelConfigurations.length > 0
        ? modelConfigurations
        : [
            {
              name: "test-model-1",
              is_visible: true,
              max_input_tokens: 4096,
              supports_image_input: false,
            },
            {
              name: "test-model-2",
              is_visible: true,
              max_input_tokens: 8192,
              supports_image_input: true,
            },
          ],
    recommended_default_model: null,
  };
}

/**
 * Creates a mock OnboardingState for testing
 */
export function createMockOnboardingState(
  overrides: Partial<OnboardingState> = {}
): OnboardingState {
  return {
    currentStep: OnboardingStep.LlmSetup,
    stepIndex: 2,
    totalSteps: 4,
    data: {
      userName: "Test User",
      llmProviders: [],
    },
    isButtonActive: false,
    isLoading: false,
    error: undefined,
    ...overrides,
  };
}

/**
 * Creates mock OnboardingActions for testing
 */
export function createMockOnboardingActions(
  overrides: Partial<OnboardingActions> = {}
): OnboardingActions {
  return {
    nextStep: jest.fn(),
    prevStep: jest.fn(),
    goToStep: jest.fn(),
    setButtonActive: jest.fn(),
    updateName: jest.fn(),
    updateData: jest.fn(),
    setLoading: jest.fn(),
    setError: jest.fn(),
    reset: jest.fn(),
    ...overrides,
  };
}

/**
 * Creates mock fetch responses for common API calls
 */
export function createMockFetchResponses() {
  return {
    testApiSuccess: {
      ok: true,
      json: async () => ({}),
    } as Response,
    testApiError: (message: string = "Invalid API key") =>
      ({
        ok: false,
        status: 400,
        json: async () => ({ detail: message }),
      }) as Response,
    createProviderSuccess: (id: number = 1) =>
      ({
        ok: true,
        json: async () => ({ id, name: "test-provider" }),
      }) as Response,
    createProviderError: (message: string = "Failed to create provider") =>
      ({
        ok: false,
        status: 500,
        json: async () => ({ detail: message }),
      }) as Response,
    setDefaultSuccess: {
      ok: true,
      json: async () => ({}),
    } as Response,
    fetchModelsSuccess: (models: { name: string }[]) =>
      ({
        ok: true,
        json: async () => models,
      }) as Response,
    fetchModelsError: (message: string = "Failed to fetch models") =>
      ({
        ok: false,
        status: 400,
        json: async () => ({ detail: message }),
      }) as Response,
  };
}

/**
 * Common form field test IDs and labels for querying
 */
export const FORM_LABELS = {
  apiKey: /api key/i,
  defaultModel: /default model/i,
  apiBaseUrl: /api base.*url/i,
  targetUri: /target uri/i,
  providerName: /provider name/i,
  awsRegion: /aws region/i,
  authMethod: /authentication method/i,
  accessKeyId: /access key id/i,
  secretAccessKey: /secret access key/i,
  credentialsFile: /credentials file/i,
};

/**
 * Waits for the modal to be open and visible
 */
export async function waitForModalOpen(screen: any, waitFor: any) {
  await waitFor(() => {
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
}

/**
 * Common provider descriptors for testing
 */
/**
 * The curated list of OpenAI visible models that are returned by
 * /api/admin/llm/built-in/options. This must match OPENAI_VISIBLE_MODEL_NAMES
 * in backend/onyx/llm/llm_provider_options.py
 */
export const OPENAI_DEFAULT_VISIBLE_MODELS = [
  {
    name: "gpt-5.2",
    is_visible: true,
    max_input_tokens: 128000,
    supports_image_input: true,
  },
  {
    name: "gpt-5-mini",
    is_visible: true,
    max_input_tokens: 128000,
    supports_image_input: true,
  },
  {
    name: "o1",
    is_visible: true,
    max_input_tokens: 200000,
    supports_image_input: true,
  },
  {
    name: "o3-mini",
    is_visible: true,
    max_input_tokens: 200000,
    supports_image_input: false,
  },
  {
    name: "gpt-4o",
    is_visible: true,
    max_input_tokens: 128000,
    supports_image_input: true,
  },
  {
    name: "gpt-4o-mini",
    is_visible: true,
    max_input_tokens: 128000,
    supports_image_input: true,
  },
];

/**
 * The curated list of Anthropic visible models that are returned by
 * /api/admin/llm/built-in/options. This must match ANTHROPIC_VISIBLE_MODEL_NAMES
 * in backend/onyx/llm/llm_provider_options.py
 */
export const ANTHROPIC_DEFAULT_VISIBLE_MODELS = [
  {
    name: "claude-opus-4-5",
    is_visible: true,
    max_input_tokens: 200000,
    supports_image_input: true,
  },
  {
    name: "claude-sonnet-4-5",
    is_visible: true,
    max_input_tokens: 200000,
    supports_image_input: true,
  },
  {
    name: "claude-haiku-4-5",
    is_visible: true,
    max_input_tokens: 200000,
    supports_image_input: true,
  },
];

/**
 * The curated list of Vertex AI visible models that are returned by
 * /api/admin/llm/built-in/options. This must match VERTEXAI_VISIBLE_MODEL_NAMES
 * in backend/onyx/llm/llm_provider_options.py
 */
export const VERTEXAI_DEFAULT_VISIBLE_MODELS = [
  {
    name: "gemini-2.5-flash",
    is_visible: true,
    max_input_tokens: 1048576,
    supports_image_input: true,
  },
  {
    name: "gemini-2.5-flash-lite",
    is_visible: true,
    max_input_tokens: 1048576,
    supports_image_input: true,
  },
  {
    name: "gemini-2.5-pro",
    is_visible: true,
    max_input_tokens: 1048576,
    supports_image_input: true,
  },
];

export const MOCK_PROVIDERS = {
  openai: createMockLLMDescriptor(
    LLMProviderName.OPENAI,
    OPENAI_DEFAULT_VISIBLE_MODELS
  ),
  anthropic: createMockLLMDescriptor(
    LLMProviderName.ANTHROPIC,
    ANTHROPIC_DEFAULT_VISIBLE_MODELS
  ),
  ollama: createMockLLMDescriptor(LLMProviderName.OLLAMA_CHAT, [
    {
      name: "llama2",
      is_visible: true,
      max_input_tokens: 4096,
      supports_image_input: false,
    },
    {
      name: "mistral",
      is_visible: true,
      max_input_tokens: 8192,
      supports_image_input: false,
    },
  ]),
  azure: createMockLLMDescriptor(LLMProviderName.AZURE, [
    {
      name: "gpt-4",
      is_visible: true,
      max_input_tokens: 8192,
      supports_image_input: true,
    },
  ]),
  bedrock: createMockLLMDescriptor(LLMProviderName.BEDROCK, [
    {
      name: "anthropic.claude-3",
      is_visible: true,
      max_input_tokens: 200000,
      supports_image_input: true,
    },
  ]),
  vertexAi: createMockLLMDescriptor(
    LLMProviderName.VERTEX_AI,
    VERTEXAI_DEFAULT_VISIBLE_MODELS
  ),
  openrouter: createMockLLMDescriptor(LLMProviderName.OPENROUTER, [
    {
      name: "openai/gpt-4",
      is_visible: true,
      max_input_tokens: 8192,
      supports_image_input: true,
    },
  ]),
};
