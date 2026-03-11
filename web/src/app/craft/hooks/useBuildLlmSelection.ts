import { useMemo, useState, useCallback } from "react";
import { LLMProviderDescriptor } from "@/interfaces/llm";
import {
  BuildLlmSelection,
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
