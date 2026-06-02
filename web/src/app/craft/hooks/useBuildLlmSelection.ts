import { useMemo, useState, useCallback } from "react";
import { LLMProviderDescriptor } from "@/lib/languageModels/types";
import {
  BuildLlmSelection,
  BUILD_MODE_PROVIDERS,
  getBuildLlmSelection,
  setBuildLlmSelection,
  clearBuildLlmSelection,
  getDefaultLlmSelection,
} from "@/app/craft/onboarding/constants";

/**
 * Hook for managing Build mode LLM selection.
 *
 * Resolution priority:
 * 1. Cookie - User's explicit selection (via onboarding or configure page)
 * 2. Smart default - via getDefaultLlmSelection()
 */
export function useBuildLlmSelection(
  llmProviders: LLMProviderDescriptor[] | undefined
) {
  const [selection, setSelectionState] = useState<BuildLlmSelection | null>(
    () => getBuildLlmSelection()
  );

  // A cookie selection is valid only if the provider exists AND its model is
  // still real — either exposed by the provider or a curated model for the type.
  // Guards stale cookies pointing at a removed/renamed model (e.g. an old default).
  const isSelectionValid = useCallback(
    (sel: BuildLlmSelection | null): boolean => {
      if (!sel || !llmProviders) return false;
      const provider = llmProviders.find((p) => p.provider === sel.provider);
      if (!provider) return false;
      if (provider.model_configurations.some((m) => m.name === sel.modelName)) {
        return true;
      }
      const curated = BUILD_MODE_PROVIDERS.find((p) => p.key === sel.provider);
      return Boolean(curated?.models.some((m) => m.name === sel.modelName));
    },
    [llmProviders]
  );

  // Compute effective selection: cookie > smart default
  const effectiveSelection = useMemo((): BuildLlmSelection | null => {
    // Use cookie if valid
    if (selection && isSelectionValid(selection)) {
      return selection;
    }

    // Fall back to smart default
    return getDefaultLlmSelection(llmProviders);
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
