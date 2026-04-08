"use client";

import { useState, useCallback, useEffect, useMemo, useRef } from "react";
import {
  MAX_MODELS,
  SelectedModel,
} from "@/refresh-components/popovers/ModelSelector";
import { LLMOverride } from "@/app/app/services/lib";
import { LlmManager } from "@/lib/hooks";
import { buildLlmOptions } from "@/refresh-components/popovers/llmUtils";

export interface UseMultiModelChatReturn {
  /** Currently selected models for multi-model comparison. */
  selectedModels: SelectedModel[];
  /** Whether multi-model mode is active (>1 model selected). */
  isMultiModelActive: boolean;
  /** Add a model to the selection. */
  addModel: (model: SelectedModel) => void;
  /** Remove a model by index. */
  removeModel: (index: number) => void;
  /** Replace a model at a specific index with a new one. */
  replaceModel: (index: number, model: SelectedModel) => void;
  /** Clear all selected models. */
  clearModels: () => void;
  /** Build the LLMOverride[] array from selectedModels. */
  buildLlmOverrides: () => LLMOverride[];
  /**
   * Restore multi-model selection from model version strings (e.g. from chat history).
   * Matches against available llmOptions to reconstruct full SelectedModel objects.
   */
  restoreFromModelNames: (modelNames: string[]) => void;
  /**
   * Switch to a single model by name (after user picks a preferred response).
   * Matches against llmOptions to find the full SelectedModel.
   */
  selectSingleModel: (modelName: string) => void;
}

export default function useMultiModelChat(
  llmManager: LlmManager
): UseMultiModelChatReturn {
  const [selectedModels, setSelectedModels] = useState<SelectedModel[]>([]);
  const [defaultInitialized, setDefaultInitialized] = useState(false);

  // Initialize with the default model from llmManager once providers load
  const llmOptions = useMemo(
    () =>
      llmManager.llmProviders ? buildLlmOptions(llmManager.llmProviders) : [],
    [llmManager.llmProviders]
  );

  // Sync selectedModels[0] with llmManager.currentLlm when in single-model
  // mode. This handles both initial load and session override changes (e.g.
  // page reload restores the persisted model after providers load).
  // Skip when user has manually added multiple models (multi-model mode).
  const selectedModelsRef = useRef(selectedModels);
  selectedModelsRef.current = selectedModels;

  useEffect(() => {
    if (llmOptions.length === 0) return;
    const { currentLlm } = llmManager;
    if (!currentLlm.modelName) return;

    const current = selectedModelsRef.current;

    // Don't override multi-model selections
    if (current.length > 1) return;

    // Skip if already showing the correct model
    if (
      current.length === 1 &&
      current[0]!.provider === currentLlm.provider &&
      current[0]!.modelName === currentLlm.modelName
    ) {
      return;
    }

    const match = llmOptions.find(
      (opt) =>
        opt.provider === currentLlm.provider &&
        opt.modelName === currentLlm.modelName
    );
    if (match) {
      setSelectedModels([
        {
          name: match.name,
          provider: match.provider,
          modelName: match.modelName,
          displayName: match.displayName,
        },
      ]);
      setDefaultInitialized(true);
    }
  }, [llmOptions, llmManager.currentLlm]);

  const isMultiModelActive = selectedModels.length > 1;

  const addModel = useCallback((model: SelectedModel) => {
    setSelectedModels((prev) => {
      if (prev.length >= MAX_MODELS) return prev;
      if (
        prev.some(
          (m) =>
            m.provider === model.provider && m.modelName === model.modelName
        )
      ) {
        return prev;
      }
      return [...prev, model];
    });
  }, []);

  const removeModel = useCallback((index: number) => {
    setSelectedModels((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const replaceModel = useCallback((index: number, model: SelectedModel) => {
    setSelectedModels((prev) => {
      // Don't replace with a model that's already selected elsewhere
      if (
        prev.some(
          (m, i) =>
            i !== index &&
            m.provider === model.provider &&
            m.modelName === model.modelName
        )
      ) {
        return prev;
      }
      const next = [...prev];
      next[index] = model;
      return next;
    });
  }, []);

  const clearModels = useCallback(() => {
    setSelectedModels([]);
  }, []);

  const restoreFromModelNames = useCallback(
    (modelNames: string[]) => {
      if (modelNames.length < 2 || llmOptions.length === 0) return;
      const restored: SelectedModel[] = [];
      for (const name of modelNames) {
        // Try matching by modelName (raw version string like "claude-opus-4-6")
        // or by displayName (friendly name like "Claude Opus 4.6")
        const match = llmOptions.find(
          (opt) =>
            opt.modelName === name ||
            opt.displayName === name ||
            opt.name === name
        );
        if (match) {
          restored.push({
            name: match.name,
            provider: match.provider,
            modelName: match.modelName,
            displayName: match.displayName,
          });
        }
      }
      if (restored.length >= 2) {
        setSelectedModels(restored.slice(0, MAX_MODELS));
        setDefaultInitialized(true);
      }
    },
    [llmOptions]
  );

  const selectSingleModel = useCallback(
    (modelName: string) => {
      if (llmOptions.length === 0) return;
      const match = llmOptions.find(
        (opt) =>
          opt.modelName === modelName ||
          opt.displayName === modelName ||
          opt.name === modelName
      );
      if (match) {
        setSelectedModels([
          {
            name: match.name,
            provider: match.provider,
            modelName: match.modelName,
            displayName: match.displayName,
          },
        ]);
      }
    },
    [llmOptions]
  );

  const buildLlmOverrides = useCallback((): LLMOverride[] => {
    return selectedModels.map((m) => ({
      model_provider: m.name,
      model_version: m.modelName,
      display_name: m.displayName,
    }));
  }, [selectedModels]);

  return {
    selectedModels,
    isMultiModelActive,
    addModel,
    removeModel,
    replaceModel,
    clearModels,
    buildLlmOverrides,
    restoreFromModelNames,
    selectSingleModel,
  };
}
