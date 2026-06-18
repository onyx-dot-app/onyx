"use client";

import { useState, useMemo, useRef } from "react";
import { getModelIcon } from "@/lib/languageModels";
import {
  Button,
  SelectButton,
  Popover,
  Divider,
  Tooltip,
} from "@opal/components";
import { SvgPlusCircle, SvgX } from "@opal/icons";
import { cn } from "@opal/utils";
import { useSettings } from "@/lib/settings/hooks";
import { LLMOption, buildLlmOptions } from "@/lib/languageModels/options";
import { useCurrentAgentLLMProviders } from "@/lib/languageModels/hooks";
import ModelSelectorContent from "@/sections/model-selector/ModelSelectorContent";

export const MAX_MODELS = 3;

export interface SelectedModel {
  name: string;
  provider: string;
  modelName: string;
  displayName: string;
}

export interface MultiModelSelectorProps {
  selectedModels: SelectedModel[];
  onAdd: (model: SelectedModel) => void;
  onRemove: (index: number) => void;
  onReplace: (index: number, model: SelectedModel) => void;
}

function modelKey(provider: string, modelName: string): string {
  return `${provider}:${modelName}`;
}

export default function MultiModelSelector({
  selectedModels,
  onAdd,
  onRemove,
  onReplace,
}: MultiModelSelectorProps) {
  const [open, setOpen] = useState(false);
  const [replacingIndex, setReplacingIndex] = useState<number | null>(null);
  const anchorRef = useRef<HTMLElement | null>(null);

  const settings = useSettings();
  const multiModelAllowed = settings.multi_model_chat_enabled ?? true;

  // Mirror the data source used by `ModelSelectorContent` so the selector is
  // disabled precisely when the popover would render "No models found".
  const { llmProviders, isLoading } = useCurrentAgentLLMProviders();
  const noModelsToSelect = useMemo(
    () => !isLoading && buildLlmOptions(llmProviders).length === 0,
    [isLoading, llmProviders]
  );

  const isMultiModel = selectedModels.length > 1;
  const atMax = selectedModels.length >= MAX_MODELS || !multiModelAllowed;

  // Single tooltip for the whole selector. The disabled reason takes
  // precedence; otherwise it labels the add affordance. When at max there is
  // no add action, so the tooltip is omitted.
  const selectorTooltip = noModelsToSelect
    ? "No models currently configured"
    : atMax
      ? undefined
      : "Add Model";

  const selectedKeys = useMemo(
    () => new Set(selectedModels.map((m) => modelKey(m.provider, m.modelName))),
    [selectedModels]
  );

  const otherSelectedKeys = useMemo(() => {
    if (replacingIndex === null) return new Set<string>();
    return new Set(
      selectedModels
        .filter((_, i) => i !== replacingIndex)
        .map((m) => modelKey(m.provider, m.modelName))
    );
  }, [selectedModels, replacingIndex]);

  const replacingKey =
    replacingIndex !== null
      ? (() => {
          const m = selectedModels[replacingIndex];
          return m ? modelKey(m.provider, m.modelName) : null;
        })()
      : null;

  const isSelected = (option: LLMOption) => {
    const key = modelKey(option.provider, option.modelName);
    if (replacingIndex !== null) return key === replacingKey;
    return selectedKeys.has(key);
  };

  const isDisabled = (option: LLMOption) => {
    const key = modelKey(option.provider, option.modelName);
    if (replacingIndex !== null) return otherSelectedKeys.has(key);
    return !selectedKeys.has(key) && atMax;
  };

  const handleSelect = (option: LLMOption) => {
    const model: SelectedModel = {
      name: option.name,
      provider: option.provider,
      modelName: option.modelName,
      displayName: option.displayName,
    };

    if (replacingIndex !== null) {
      onReplace(replacingIndex, model);
      setOpen(false);
      setReplacingIndex(null);
      return;
    }

    const key = modelKey(option.provider, option.modelName);
    const existingIndex = selectedModels.findIndex(
      (m) => modelKey(m.provider, m.modelName) === key
    );
    if (existingIndex >= 0) {
      onRemove(existingIndex);
    } else if (!atMax) {
      onAdd(model);
      if (selectedModels.length + 1 >= MAX_MODELS) {
        setOpen(false);
      }
    }
  };

  const handleOpenChange = (nextOpen: boolean) => {
    if (nextOpen && noModelsToSelect) return;
    setOpen(nextOpen);
    if (!nextOpen) setReplacingIndex(null);
  };

  const handlePillClick = (index: number, element: HTMLElement) => {
    // `pointer-events-none` only blocks the mouse; guard the keyboard path too.
    if (noModelsToSelect) return;
    anchorRef.current = element;
    setReplacingIndex(index);
    setOpen(true);
  };

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      {/*
        When disabled, pointer events are blocked on the children (so the add
        button / pills are inert) while the container itself stays hoverable, so
        the Tooltip can still surface its message even in the disabled state.
      */}
      <Tooltip tooltip={selectorTooltip} side="top">
        <div
          data-testid="model-selector"
          aria-disabled={noModelsToSelect || undefined}
          className={cn(
            "flex items-center justify-end gap-1 p-1",
            noModelsToSelect &&
              "cursor-not-allowed select-none opacity-50 [&>*]:pointer-events-none"
          )}
        >
          {!atMax && (
            <Button
              prominence="tertiary"
              icon={SvgPlusCircle}
              size="sm"
              onClick={(e: React.MouseEvent) => {
                if (noModelsToSelect) return;
                anchorRef.current = e.currentTarget as HTMLElement;
                setReplacingIndex(null);
                setOpen(true);
              }}
            />
          )}

          <Popover.Anchor
            virtualRef={anchorRef as React.RefObject<HTMLElement>}
          />
          {selectedModels.length > 0 && (
            <>
              {!atMax && (
                <Divider
                  orientation="vertical"
                  paddingParallel="sm"
                  paddingPerpendicular="sm"
                />
              )}
              <div className="flex items-center shrink-0">
                {selectedModels.map((model, index) => {
                  const ProviderIcon = getModelIcon(
                    model.provider,
                    model.modelName
                  );

                  return (
                    <div
                      key={
                        isMultiModel
                          ? modelKey(model.provider, model.modelName)
                          : "single-model-pill"
                      }
                      className="flex items-center"
                    >
                      {index > 0 && (
                        <Divider
                          orientation="vertical"
                          paddingParallel="sm"
                          paddingPerpendicular="sm"
                        />
                      )}
                      <SelectButton
                        icon={ProviderIcon}
                        rightIcon={isMultiModel ? SvgX : undefined}
                        state="empty"
                        variant="select-input"
                        size="lg"
                        onClick={(e: React.MouseEvent) => {
                          if (isMultiModel) {
                            const target = e.target as HTMLElement;
                            const btn = e.currentTarget as HTMLElement;
                            const icons = btn.querySelectorAll(
                              ".interactive-foreground-icon"
                            );
                            const lastIcon = icons[icons.length - 1];
                            if (lastIcon && lastIcon.contains(target)) {
                              onRemove(index);
                              return;
                            }
                          }
                          handlePillClick(
                            index,
                            e.currentTarget as HTMLElement
                          );
                        }}
                      >
                        {model.displayName}
                      </SelectButton>
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </div>
      </Tooltip>

      {!(atMax && replacingIndex === null) && (
        <Popover.Content side="top" align="end" width="xl">
          <ModelSelectorContent
            onSelect={handleSelect}
            isSelected={isSelected}
            isDisabled={isDisabled}
          />
        </Popover.Content>
      )}
    </Popover>
  );
}
