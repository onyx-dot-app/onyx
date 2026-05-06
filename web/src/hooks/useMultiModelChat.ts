"use client";

import { useState, useCallback, useMemo } from "react";
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

  // Initialize with the default model from llmManager once providers load
  const llmOptions = useMemo(
    () =>
      llmManager.llmProviders ? buildLlmOptions(llmManager.llmProviders) : [],
    [llmManager.llmProviders]
  );

  // In single-model mode, derive the displayed model directly from
  // llmManager.currentLlm so it always stays in sync (no stale state).
  // Only use the selectedModels state array when the user has manually
  // added multiple models (multi-model mode).
  const currentLlmModel = useMemo((): SelectedModel | null => {
    if (llmOptions.length === 0) return null;
    const { currentLlm } = llmManager;
    if (!currentLlm.modelName) return null;
    const match = llmOptions.find(
      (opt) =>
        opt.provider === currentLlm.provider &&
        opt.modelName === currentLlm.modelName
    );
    if (!match) return null;
    return {
      name: match.name,
      provider: match.provider,
      modelName: match.modelName,
      displayName: match.displayName,
    };
  }, [llmOptions, llmManager.currentLlm]);

  const isMultiModelActive = selectedModels.length > 1;

  // Expose the effective selection: multi-model state when active,
  // otherwise the single model derived from llmManager.
  const effectiveSelectedModels = useMemo(
    () =>
      isMultiModelActive
        ? selectedModels
        : currentLlmModel
          ? [currentLlmModel]
          : [],
    [isMultiModelActive, selectedModels, currentLlmModel]
  );

  const addModel = useCallback(
    (model: SelectedModel) => {
      setSelectedModels((prev) => {
        // When in effective single-model mode (prev <= 1), always re-seed from
        // the current derived model so stale state from a prior remove doesn't persist.
        const base =
          prev.length <= 1 && currentLlmModel ? [currentLlmModel] : prev;
        if (base.length >= MAX_MODELS) return base;
        if (
          base.some(
            (m) =>
              m.provider === model.provider && m.modelName === model.modelName
          )
        ) {
          return base;
        }
        return [...base, model];
      });
    },
    [currentLlmModel]
  );

  const removeModel = useCallback(
    (index: number) => {
      const next = selectedModels.filter((_, i) => i !== index);
      // When dropping to single-model, switch llmManager to the surviving
      // model so it becomes the active model instead of reverting to the
      // user's default.
      if (next.length === 1 && next[0]) {
        llmManager.updateCurrentLlm({
          name: next[0].name,
          provider: next[0].provider,
          modelName: next[0].modelName,
        });
      }
      setSelectedModels(next);
    },
    [selectedModels, llmManager]
  );

  const replaceModel = useCallback(
    (index: number, model: SelectedModel) => {
      // In single-model mode, update llmManager directly so currentLlm
      // (and thus effectiveSelectedModels) reflects the change immediately.
      if (!isMultiModelActive) {
        llmManager.updateCurrentLlm({
          name: model.name,
          provider: model.provider,
          modelName: model.modelName,
        });
        return;
      }
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
    },
    [isMultiModelActive, llmManager]
  );

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
    return effectiveSelectedModels.map((m) => ({
      model_provider: m.name,
      model_version: m.modelName,
      display_name: m.displayName,
    }));
  }, [effectiveSelectedModels]);

  return {
    selectedModels: effectiveSelectedModels,
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
