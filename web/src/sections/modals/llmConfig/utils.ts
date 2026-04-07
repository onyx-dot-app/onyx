import {
  LLMProviderView,
  ModelConfiguration,
  WellKnownLLMProviderDescriptor,
} from "@/interfaces/llm";
import * as Yup from "yup";
import { ScopedMutator } from "swr";
import { OnboardingActions, OnboardingState } from "@/interfaces/onboarding";

/** Shared initial values for all LLM provider forms (both onboarding and admin). */
export function buildInitialValues(existingLlmProvider?: LLMProviderView) {
  return {
    name: existingLlmProvider?.name ?? "",
    is_public: existingLlmProvider?.is_public ?? true,
    is_auto_mode: existingLlmProvider?.is_auto_mode ?? false,
    groups: existingLlmProvider?.groups ?? [],
    personas: existingLlmProvider?.personas ?? [],
    visible_model_names:
      existingLlmProvider?.model_configurations
        ?.filter((m) => m.is_visible)
        .map((m) => m.name) ?? [],
  };
}

interface ValidationSchemaOptions {
  apiKey?: boolean;
  apiBase?: boolean;
  extra?: Yup.ObjectShape;
}

/**
 * Builds the validation schema for a modal.
 *
 * @param isOnboarding — controls the base schema:
 *   - `true`:  minimal (only `test_model_name`).
 *   - `false`: full admin schema (display name, access, models, etc.).
 * @param options.apiKey — require `api_key`.
 * @param options.apiBase — require `api_base`.
 * @param options.extra — arbitrary Yup fields for provider-specific validation.
 */
export function buildValidationSchema(
  isOnboarding: boolean,
  { apiKey, apiBase, extra }: ValidationSchemaOptions = {}
) {
  const providerFields: Yup.ObjectShape = {
    ...(apiKey && {
      api_key: Yup.string().required("API Key is required"),
    }),
    ...(apiBase && {
      api_base: Yup.string().required("API Base URL is required"),
    }),
    ...extra,
  };

  if (isOnboarding) {
    return Yup.object().shape({
      test_model_name: Yup.string().required("Model name is required"),
      ...providerFields,
    });
  }

  return Yup.object({
    name: Yup.string().required("Display Name is required"),
    is_public: Yup.boolean().required(),
    is_auto_mode: Yup.boolean().required(),
    groups: Yup.array().of(Yup.number()),
    personas: Yup.array().of(Yup.number()),
    test_model_name: Yup.string().required("Model name is required"),
    visible_model_names: Yup.array().of(Yup.string()),
    ...providerFields,
  });
}

export function buildAvailableModelConfigurations(
  existingLlmProvider?: LLMProviderView,
  wellKnownLLMProvider?: WellKnownLLMProviderDescriptor
): ModelConfiguration[] {
  const existingModels = existingLlmProvider?.model_configurations ?? [];
  const wellKnownModels = wellKnownLLMProvider?.known_models ?? [];

  // Create a map to deduplicate by model name, preferring existing models
  const modelMap = new Map<string, ModelConfiguration>();

  // Add well-known models first
  wellKnownModels.forEach((model) => {
    modelMap.set(model.name, model);
  });

  // Override with existing models (they take precedence)
  existingModels.forEach((model) => {
    modelMap.set(model.name, model);
  });

  return Array.from(modelMap.values());
}

// ─── Form value types ─────────────────────────────────────────────────────

/** Base form values that all provider forms share. */
export interface BaseLLMFormValues {
  name: string;
  api_key?: string;
  api_base?: string;
  /** Model name used for the test request — not sent to the backend. */
  test_model_name?: string;
  is_public: boolean;
  is_auto_mode: boolean;
  groups: number[];
  personas: number[];
  /** User-selected visible models — not sent to the backend directly;
   *  used to compute model_configurations[].is_visible. */
  visible_model_names: string[];
  custom_config?: Record<string, string>;
}

// ─── Submit params ────────────────────────────────────────────────────────

export interface SubmitLLMProviderParams<
  T extends BaseLLMFormValues = BaseLLMFormValues,
> {
  providerName: string;
  values: T;
  initialValues: T;
  modelConfigurations: ModelConfiguration[];
  existingLlmProvider?: LLMProviderView;
  shouldMarkAsDefault?: boolean;
  hideSuccess?: boolean;
  setStatus: (status: Record<string, unknown>) => void;
  mutate: ScopedMutator;
  onClose: () => void;
  setSubmitting: (submitting: boolean) => void;
}

// ─── Model configuration helpers ──────────────────────────────────────────

/** Sets is_visible based on the user's selection and filters out unselected models. */
export function filterModelConfigurations(
  currentModelConfigurations: ModelConfiguration[],
  visibleModels: string[],
  testModelName?: string
): ModelConfiguration[] {
  return currentModelConfigurations
    .map(
      (modelConfiguration): ModelConfiguration => ({
        name: modelConfiguration.name,
        is_visible: visibleModels.includes(modelConfiguration.name),
        max_input_tokens: modelConfiguration.max_input_tokens ?? null,
        supports_image_input: modelConfiguration.supports_image_input,
        supports_reasoning: modelConfiguration.supports_reasoning,
        display_name: modelConfiguration.display_name,
      })
    )
    .filter(
      (modelConfiguration) =>
        modelConfiguration.name === testModelName ||
        modelConfiguration.is_visible
    );
}

/** In auto mode, include ALL models but preserve their visibility status. */
export function getAutoModeModelConfigurations(
  modelConfigurations: ModelConfiguration[]
): ModelConfiguration[] {
  return modelConfigurations.map(
    (modelConfiguration): ModelConfiguration => ({
      name: modelConfiguration.name,
      is_visible: modelConfiguration.is_visible,
      max_input_tokens: modelConfiguration.max_input_tokens ?? null,
      supports_image_input: modelConfiguration.supports_image_input,
      supports_reasoning: modelConfiguration.supports_reasoning,
      display_name: modelConfiguration.display_name,
    })
  );
}

// ─── Misc ─────────────────────────────────────────────────────────────────

export type TestApiKeyResult =
  | { ok: true }
  | { ok: false; errorMessage: string };

export interface SubmitOnboardingProviderParams {
  providerName: string;
  payload: Record<string, unknown>;
  onboardingState: OnboardingState;
  onboardingActions: OnboardingActions;
  isCustomProvider: boolean;
  onClose: () => void;
  setIsSubmitting: (submitting: boolean) => void;
}
