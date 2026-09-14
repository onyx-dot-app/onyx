import {
  LLMProviderName,
  type LLMProviderView,
  type WellKnownLLMProviderDescriptor,
  type ModelConfiguration,
  type ReasoningEffortOverride,
} from "@/lib/languageModels/types";
import {
  ALL_REASONING_STOPS,
  maxReasoningStop,
} from "@/sections/model-selector/setting-controls";
import * as Yup from "yup";
import type { useTranslations } from "next-intl";
import { useWellKnownLLMProvider } from "@/lib/languageModels/hooks";

/** Translator for the `admin.languageModels.modals` namespace, threaded into
 *  helpers that live outside a component and so cannot call the hook. */
export type LlmModalsTranslator = ReturnType<
  typeof useTranslations<"admin.languageModels.modals">
>;

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

  return Array.from(modelMap.values()).map(clampModelSettings);
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
    id: existingLlmProvider?.id,
    provider: existingLlmProvider?.provider ?? providerName,
    name: isOnboarding
      ? providerName
      : (existingLlmProvider?.name ?? undefined),
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
 * @param t — translator for the modal namespace.
 * @param isOnboarding — controls the base schema:
 *   - `true`:  minimal (only `test_model_name`).
 *   - `false`: full admin schema (display name, access, models, etc.).
 * @param options.apiKey — require `api_key`.
 * @param options.apiBase — require `api_base`.
 * @param options.extra — arbitrary Yup fields for provider-specific validation.
 */
export function buildValidationSchema(
  t: LlmModalsTranslator,
  isOnboarding: boolean,
  { apiKey, apiBase, extra }: ValidationSchemaOptions = {}
) {
  const providerFields: Yup.ObjectShape = {
    ...(apiKey && {
      api_key: Yup.string().required(t("validation.apiKeyRequired")),
    }),
    ...(apiBase && {
      api_base: Yup.string().required(t("validation.apiBaseRequired")),
    }),
    ...extra,
  };

  if (isOnboarding) {
    return Yup.object().shape({
      test_model_name: Yup.string().required(t("validation.modelNameRequired")),
      ...providerFields,
    });
  }

  return Yup.object({
    name: Yup.string().optional(),
    is_public: Yup.boolean().required(),
    is_auto_mode: Yup.boolean().required(),
    groups: Yup.array().of(Yup.number()),
    personas: Yup.array().of(Yup.number()),
    test_model_name: Yup.string().required(t("validation.modelNameRequired")),
    ...providerFields,
  });
}

// ─── Form value types ─────────────────────────────────────────────────────

/** Base form values that all provider forms share. */
export interface BaseLLMFormValues {
  id?: number;
  name?: string;
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

/** Bound stored policy by current capability, which can shrink after a save. */
export function clampModelSettings<
  T extends Pick<
    ModelConfiguration,
    | "supported_reasoning_efforts"
    | "reasoning_effort_max"
    | "reasoning_effort_default"
  >,
>(model: T): T {
  const highestIndex = maxReasoningStop(model.supported_reasoning_efforts);
  if (highestIndex < 0) return model;
  const bound = (effort: ReasoningEffortOverride | null | undefined) =>
    effort && ALL_REASONING_STOPS.indexOf(effort) > highestIndex
      ? ALL_REASONING_STOPS[highestIndex]
      : effort;
  return {
    ...model,
    reasoning_effort_max: bound(model.reasoning_effort_max),
    reasoning_effort_default: bound(model.reasoning_effort_default),
  };
}

// ─── mergeFetchedModelConfigurations ──────────────────────────────────────

/**
 * Merges a freshly-fetched model list with the current form state so that
 * refreshing the model list does not clobber the user's selections. Call it
 * from a functional `setValues` so a fetch that lands late cannot revert edits
 * made while it was in flight.
 *
 * - If the form has no models yet (first fetch / onboarding), the fetched
 *   list is used with only settings clamped, so each provider's own default
 *   `is_visible` applies.
 * - Otherwise, models that already exist in the form keep their prior unsaved
 *   edits (visibility, rename, admin settings), and newly-discovered models are
 *   added unselected so the user can opt-in explicitly.
 */
export function mergeFetchedModelConfigurations(
  fetched: ModelConfiguration[],
  existing: ModelConfiguration[]
): ModelConfiguration[] {
  if (existing.length === 0) return fetched.map(clampModelSettings);
  const priorByName = new Map(existing.map((m) => [m.name, m]));
  return fetched.map((model) => {
    const prior = priorByName.get(model.name);
    if (!prior) return clampModelSettings({ ...model, is_visible: false });
    // Unsaved edits live only in form state, so a refetch has to carry them.
    return clampModelSettings({
      ...model,
      is_visible: prior.is_visible,
      custom_display_name: prior.custom_display_name,
      reasoning_effort_max: prior.reasoning_effort_max,
      reasoning_effort_default: prior.reasoning_effort_default,
      temperature_default: prior.temperature_default,
    });
  });
}

/** Functional `setValues` updater applying {@link mergeFetchedModelConfigurations}. */
export function withFetchedModels<
  T extends { model_configurations: ModelConfiguration[] },
>(fetched: ModelConfiguration[]) {
  return (prev: T): T => ({
    ...prev,
    model_configurations: mergeFetchedModelConfigurations(
      fetched,
      prev.model_configurations
    ),
  });
}

// ─── Misc ─────────────────────────────────────────────────────────────────

export type TestApiKeyResult =
  | { ok: true }
  | { ok: false; errorMessage: string };
