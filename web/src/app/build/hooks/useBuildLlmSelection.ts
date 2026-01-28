import { useMemo, useState, useCallback } from "react";
import { LLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import {
  BuildLlmSelection,
  getBuildLlmSelection,
  setBuildLlmSelection,
  clearBuildLlmSelection,
  RECOMMENDED_BUILD_MODELS,
} from "@/app/build/onboarding/constants";

/**
 * Hook for managing Build mode LLM selection.
 *
 * Resolution priority:
 * 1. Cookie - User's explicit selection (via onboarding or configure page)
 * 2. Smart default - Anthropic Opus 4.5 if available and no cookie exists
 * 3. System default - System default provider if no Anthropic and no cookie
 */
export function useBuildLlmSelection(
  llmProviders: LLMProviderDescriptor[] | undefined
) {
  const [selection, setSelectionState] = useState<BuildLlmSelection | null>(
    () => getBuildLlmSelection()
  );

  // Validate that a selection is still valid against current providers.
  // Only checks that the provider exists
  const isSelectionValid = useCallback(
    (sel: BuildLlmSelection | null): boolean => {
      if (!sel || !llmProviders) return false;
      return llmProviders.some(
        (p) => p.provider === sel.provider || p.name === sel.providerName
      );
    },
    [llmProviders]
  );

  // Compute effective selection: cookie > smart default > system default
  const effectiveSelection = useMemo((): BuildLlmSelection | null => {
    if (!llmProviders || llmProviders.length === 0) return null;

    // 1. Use cookie if valid
    if (selection && isSelectionValid(selection)) {
      return selection;
    }

    // 2. Smart default: Anthropic Opus 4.5 if Anthropic provider is configured
    const anthropicProvider = llmProviders.find(
      (p) =>
        p.provider === "anthropic" || p.name.toLowerCase().includes("anthropic")
    );
    if (anthropicProvider) {
      return {
        providerName: anthropicProvider.name,
        provider: anthropicProvider.provider,
        modelName: RECOMMENDED_BUILD_MODELS.preferred.modelName,
      };
    }

    // 3. Fall back to system default provider
    const defaultProvider = llmProviders.find((p) => p.is_default_provider);
    if (defaultProvider) {
      return {
        providerName: defaultProvider.name,
        provider: defaultProvider.provider,
        modelName: defaultProvider.default_model_name,
      };
    }

    // 4. First available provider
    const firstProvider = llmProviders[0];
    if (firstProvider) {
      return {
        providerName: firstProvider.name,
        provider: firstProvider.provider,
        modelName: firstProvider.default_model_name,
      };
    }

    return null;
  }, [selection, llmProviders, isSelectionValid]);

  // Update selection and persist to cookie
  const updateSelection = useCallback((newSelection: BuildLlmSelection) => {
    setBuildLlmSelection(newSelection);
    setSelectionState(newSelection);
  }, []);

  // Clear selection (removes cookie)
  const clearSelection = useCallback(() => {
    clearBuildLlmSelection();
    setSelectionState(null);
  }, []);

  return {
    selection: effectiveSelection,
    updateSelection,
    clearSelection,
    isFromCookie: selection !== null && isSelectionValid(selection),
  };
}
