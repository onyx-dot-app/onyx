"use client";

import { useState, useMemo } from "react";
import Popover from "@/refresh-components/Popover";
import { LlmManager } from "@/lib/hooks";
import { getProviderIcon } from "@/app/admin/configuration/llm/utils";
import { Button, SelectButton, OpenButton } from "@opal/components";
import { SvgPlusCircle, SvgX } from "@opal/icons";
import { LLMOption } from "@/refresh-components/popovers/interfaces";
import ModelListContent from "@/refresh-components/popovers/ModelListContent";
import Separator from "@/refresh-components/Separator";

export const MAX_MODELS = 3;

export interface SelectedModel {
  name: string;
  provider: string;
  modelName: string;
  displayName: string;
}

export interface ModelSelectorProps {
  llmManager: LlmManager;
  selectedModels: SelectedModel[];
  onAdd: (model: SelectedModel) => void;
  onRemove: (index: number) => void;
  onReplace: (index: number, model: SelectedModel) => void;
}

function modelKey(provider: string, modelName: string): string {
  return `${provider}:${modelName}`;
}

export default function ModelSelector({
  llmManager,
  selectedModels,
  onAdd,
  onRemove,
  onReplace,
}: ModelSelectorProps) {
  const [open, setOpen] = useState(false);
  // null = add mode (via + button), number = replace mode (via pill click)
  const [replacingIndex, setReplacingIndex] = useState<number | null>(null);

  const isMultiModel = selectedModels.length > 1;
  const atMax = selectedModels.length >= MAX_MODELS;

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
    }
  };

  const handleOpenChange = (nextOpen: boolean) => {
    setOpen(nextOpen);
    if (!nextOpen) setReplacingIndex(null);
  };

  const handlePillClick = (index: number) => {
    setReplacingIndex(index);
    setOpen(true);
  };

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      <div className="flex items-center justify-end gap-1 p-1">
        {!atMax && (
          <Popover.Trigger asChild>
            <Button
              prominence="tertiary"
              icon={SvgPlusCircle}
              size="sm"
              tooltip="Add Model"
            />
          </Popover.Trigger>
        )}

        {selectedModels.length > 0 && (
          <>
            {!atMax && (
              <Separator
                orientation="vertical"
                paddingXRem={0.5}
                paddingYRem={0.5}
              />
            )}
            <Popover.Anchor asChild>
              <div className="flex items-center">
                {selectedModels.map((model, index) => {
                  const ProviderIcon = getProviderIcon(
                    model.provider,
                    model.modelName
                  );

                  if (!isMultiModel) {
                    return (
                      <OpenButton
                        key={modelKey(model.provider, model.modelName)}
                        icon={ProviderIcon}
                        onClick={() => handlePillClick(index)}
                      >
                        {model.displayName}
                      </OpenButton>
                    );
                  }

                  return (
                    <div
                      key={modelKey(model.provider, model.modelName)}
                      className="flex items-center"
                    >
                      {index > 0 && (
                        <Separator
                          orientation="vertical"
                          paddingXRem={0.5}
                          className="h-5"
                        />
                      )}
                      <SelectButton
                        icon={ProviderIcon}
                        rightIcon={SvgX}
                        state="empty"
                        variant="select-tinted"
                        interaction="hover"
                        size="lg"
                        onClick={(e: React.MouseEvent) => {
                          const target = e.target as HTMLElement;
                          const btn = e.currentTarget as HTMLElement;
                          const icons = btn.querySelectorAll(
                            ".interactive-foreground-icon"
                          );
                          const lastIcon = icons[icons.length - 1];
                          if (lastIcon && lastIcon.contains(target)) {
                            onRemove(index);
                          } else {
                            handlePillClick(index);
                          }
                        }}
                      >
                        {model.displayName}
                      </SelectButton>
                    </div>
                  );
                })}
              </div>
            </Popover.Anchor>
          </>
        )}
      </div>

      <Popover.Content side="top" align="start" width="lg">
        <ModelListContent
          llmProviders={llmManager.llmProviders}
          isLoading={llmManager.isLoadingProviders}
          onSelect={handleSelect}
          isSelected={isSelected}
          isDisabled={isDisabled}
        />
      </Popover.Content>
    </Popover>
  );
}
