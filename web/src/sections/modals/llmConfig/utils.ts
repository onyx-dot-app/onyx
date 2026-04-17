import {
  LLMProviderName,
  LLMProviderView,
  ModelConfiguration,
  WellKnownLLMProviderDescriptor,
} from "@/interfaces/llm";
import * as Yup from "yup";
import { useWellKnownLLMProvider } from "@/hooks/useLLMProviders";

// ─── useInitialValues ─────────────────────────────────────────────────────

/** Builds the merged model list from existing + well-known, deduped by name. */
function buildModelConfigurations(
  existingLlmProvider?: LLMProviderView,
  wellKnownLLMProvider?: WellKnownLLMProviderDescriptor
): ModelConfiguration[] {
  const existingModels = existingLlmProvider?.model_configurations ?? [];
  const wellKnownModels = wellKnownLLMProvider?.known_models ?? [];

  const modelMap = new Map<string, ModelConfiguration>();
  wellKnownModels.forEach((m) => modelMap.set(m.name, m));
  existingModels.forEach((m) => modelMap.set(m.name, m));

  return Array.from(modelMap.values());
}

/** Shared initial values for all LLM provider forms (both onboarding and admin). */
export function useInitialValues(
  isOnboarding: boolean,
  providerName: LLMProviderName,
  existingLlmProvider?: LLMProviderView
) {
  const { wellKnownLLMProvider } = useWellKnownLLMProvider(providerName);

  const modelConfigurations = buildModelConfigurations(
    existingLlmProvider,
    wellKnownLLMProvider ?? undefined
  );

  const testModelName =
    modelConfigurations.find((m) => m.is_visible)?.name ??
    wellKnownLLMProvider?.recommended_default_model?.name;

  return {
    provider: existingLlmProvider?.provider ?? providerName,
    name: isOnboarding ? providerName : existingLlmProvider?.name ?? "",
    api_key: existingLlmProvider?.api_key ?? undefined,
    api_base: existingLlmProvider?.api_base ?? undefined,
    is_public: existingLlmProvider?.is_public ?? true,
    is_auto_mode: existingLlmProvider?.is_auto_mode ?? true,
    groups: existingLlmProvider?.groups ?? [],
    personas: existingLlmProvider?.personas ?? [],
    model_configurations: modelConfigurations,
    test_model_name: testModelName,
  };
}

// ─── buildValidationSchema ────────────────────────────────────────────────

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
    ...providerFields,
  });
}

// ─── Form value types ─────────────────────────────────────────────────────

/** Base form values that all provider forms share. */
export interface BaseLLMFormValues {
  name: string;
  api_key?: string;
  api_base?: string;
  /** Model name used for the test request — automatically derived. */
  test_model_name?: string;
  is_public: boolean;
  is_auto_mode: boolean;
  groups: number[];
  personas: number[];
  /** The full model list with is_visible set directly by user interaction. */
  model_configurations: ModelConfiguration[];
  custom_config?: Record<string, string>;
}

// ─── mergeFetchedModelConfigurations ──────────────────────────────────────

/**
 * Merges a freshly-fetched model list with the current form state so that
 * refreshing the model list does not clobber the user's selections.
 *
 * - If the form has no models yet (first fetch / onboarding), the fetched
 *   list is returned as-is so each provider's own default `is_visible` applies.
 * - Otherwise, models that already exist in the form keep their prior
 *   `is_visible` value, and newly-discovered models are added unselected so
 *   the user can opt-in explicitly.
 */
export function mergeFetchedModelConfigurations(
  fetched: ModelConfiguration[],
  existing: ModelConfiguration[]
): ModelConfiguration[] {
  if (existing.length === 0) return fetched;
  const priorByName = new Map(existing.map((m) => [m.name, m]));
  return fetched.map((model) => {
    const prior = priorByName.get(model.name);
    return { ...model, is_visible: prior ? prior.is_visible : false };
  });
}

// ─── Misc ─────────────────────────────────────────────────────────────────

export type TestApiKeyResult =
  | { ok: true }
  | { ok: false; errorMessage: string };
