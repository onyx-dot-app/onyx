"use client";

import { useState, useMemo, useRef } from "react";
import { useTranslations } from "next-intl";
import { getModelIcon } from "@/lib/languageModels/utils";
import {
  Button,
  SelectButton,
  Popover,
  Divider,
  Tooltip,
} from "@opal/components";
import { SvgPlusCircle, SvgSparkle, SvgX } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import { cn } from "@opal/utils";
import { useSettings } from "@/lib/settings/hooks";
import { buildLlmOptions, llmOptionKey } from "@/lib/languageModels/options";
import { useLanguageModelsForCurrentAgent } from "@/lib/languageModels/hooks";
import ModelSelectorContent, {
  ReasoningManager,
  TemperatureManager,
  useModelDetailManagers,
} from "@/sections/model-selector/ModelSelectorContent";
import type { LLMOption } from "@/lib/languageModels/types";

export const MAX_MODELS = 3;

export interface SelectedModel {
  name: string;
  provider: string;
  modelName: string;
  /** Unique id of the model configuration; disambiguates same-named models across providers. */
  modelConfigurationId: number | null;
  displayName: string;
}

export interface MultiModelSelectorProps {
  selectedModels: SelectedModel[];
  onAdd: (model: SelectedModel) => void;
  onRemove: (index: number) => void;
  onReplace: (index: number, model: SelectedModel) => void;
  /** See ModelSelectorProps. Powers the per-model detail pane. */
  temperatureManager?: TemperatureManager;
  reasoningManager?: ReasoningManager;
}

/** Floating UI virtual element behind Radix's virtualRef; `contextElement` gets the scroll, resize and layout observers. */
interface PopoverAnchor {
  getBoundingClientRect(): DOMRect;
  readonly contextElement?: Element;
}

export default function MultiModelSelector({
  selectedModels,
  onAdd,
  onRemove,
  onReplace,
  temperatureManager,
  reasoningManager,
}: MultiModelSelectorProps) {
  const t = useTranslations("chat.modelSelector");
  const [open, setOpen] = useState(false);
  // The pill whose switch list is open; null for the add list.
  const [switchIndex, setSwitchIndex] = useState<number | null>(null);
  // Remounts the content per open, so a menu opened over another starts on its list.
  const [menuKey, setMenuKey] = useState(0);
  const rowRef = useRef<HTMLDivElement>(null);
  // The opener's rect frozen at open: a pick can move or unmount the opener
  // (pills prepend, + hides at max, a replaced pill remounts) while the menu fades.
  const anchorRef = useRef<PopoverAnchor>({
    getBoundingClientRect: () => new DOMRect(),
  });

  const settings = useSettings();
  const multiModelAllowed = settings.multi_model_chat_enabled ?? true;
  const routingEnabled: boolean =
    (settings.model_routing_enabled ?? false) &&
    settings.model_routing_model_configuration_id != null;
  const routingModelId: number | null | undefined =
    settings.model_routing_model_configuration_id;

  const modelDetail = useModelDetailManagers(
    temperatureManager,
    reasoningManager
  );

  // Mirror the data source used by `ModelSelectorContent` so the selector is
  // disabled precisely when the popover would render "No models found".
  const { llmProviders, isLoading } = useLanguageModelsForCurrentAgent();
  const noModelsToSelect = useMemo(
    () => !isLoading && buildLlmOptions(llmProviders).length === 0,
    [isLoading, llmProviders]
  );

  const isMultiModel = selectedModels.length > 1;
  const canAdd: boolean =
    multiModelAllowed && selectedModels.length < MAX_MODELS;

  // Container-level tooltip carries only the disabled reason. The add button
  // labels itself, so an enabled row shows no tooltip outside the button.
  const selectorTooltip = noModelsToSelect
    ? t("multiModel.noModels.tooltip")
    : undefined;

  const selectedKeys = useMemo(
    () => new Set(selectedModels.map(llmOptionKey)),
    [selectedModels]
  );

  const switchModel: SelectedModel | undefined =
    switchIndex === null ? undefined : selectedModels[switchIndex];
  const switchKey: string | null = switchModel
    ? llmOptionKey(switchModel)
    : null;

  const isSelected = (option: LLMOption) => {
    const key = llmOptionKey(option);
    if (switchIndex !== null) return key === switchKey;
    return selectedKeys.has(key);
  };

  // The switch list cannot pick a model another pill already shows.
  const isDisabled = (option: LLMOption) => {
    const key = llmOptionKey(option);
    const selected: boolean = selectedKeys.has(key);
    if (switchIndex !== null) return selected && key !== switchKey;
    return !selected && !canAdd;
  };

  const toSelectedModel = (option: LLMOption): SelectedModel => ({
    name: option.name,
    provider: option.provider,
    modelName: option.modelName,
    modelConfigurationId: option.modelConfigurationId ?? null,
    displayName: option.displayName,
  });

  const handleOpenChange = (nextOpen: boolean) => {
    if (nextOpen && noModelsToSelect) return;
    setOpen(nextOpen);
    if (!nextOpen) setSwitchIndex(null);
  };

  const handleSelect = (option: LLMOption) => {
    // The content still takes clicks while it fades out after a pick.
    if (!open) return;
    const key = llmOptionKey(option);

    if (switchIndex !== null) {
      if (key !== switchKey) onReplace(switchIndex, toSelectedModel(option));
      handleOpenChange(false);
      return;
    }

    const existingIndex = selectedModels.findIndex(
      (m) => llmOptionKey(m) === key
    );
    if (existingIndex >= 0) {
      // The sole model stays: single-model chat always needs one.
      if (!isMultiModel) return;
      onRemove(existingIndex);
    } else {
      if (!canAdd) return;
      onAdd(toSelectedModel(option));
    }
    handleOpenChange(false);
  };

  const openPicker = (element: HTMLElement, index: number | null) => {
    // `pointer-events-none` only blocks the mouse; guard the keyboard path too.
    if (noModelsToSelect) return;
    const rect: DOMRect = element.getBoundingClientRect();
    anchorRef.current = {
      getBoundingClientRect: () => rect,
      contextElement: rowRef.current ?? undefined,
    };
    setSwitchIndex(index);
    setMenuKey((key) => key + 1);
    setOpen(true);
  };

  // A multi-model pill's last foreground icon is its x.
  const isRemoveIcon = (pill: Element, target: EventTarget | null): boolean => {
    if (!isMultiModel) return false;
    const icons = pill.querySelectorAll(".interactive-foreground-icon");
    const lastIcon = icons[icons.length - 1];
    return !!lastIcon && target instanceof Node && lastIcon.contains(target);
  };

  // Popover dismisses an outside click only after the click's own handlers
  // ran, so it would close the menu a + or pill click just opened. The x still dismisses.
  const keepOpenForOpener = (event: CustomEvent<{ originalEvent: Event }>) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const opener = target.closest("button");
    if (!opener || !rowRef.current?.contains(opener)) return;
    if (isRemoveIcon(opener, target)) return;
    event.preventDefault();
  };

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      {/* Disabled state blocks pointer events on children only, so the
          container stays hoverable and this Tooltip can surface the reason. */}
      <Tooltip tooltip={selectorTooltip} side="top">
        <div
          ref={rowRef}
          data-testid="model-selector"
          aria-disabled={noModelsToSelect || undefined}
          className={cn(
            "flex items-center justify-end gap-1 p-1",
            noModelsToSelect &&
              "cursor-not-allowed select-none opacity-50 [&>*]:pointer-events-none"
          )}
        >
          {canAdd && (
            <Button
              prominence="tertiary"
              icon={SvgPlusCircle}
              size="sm"
              tooltip={t("multiModel.addModelButton.label")}
              aria-label={t("multiModel.addModelButton.label")}
              onClick={(e: React.MouseEvent<HTMLElement>) =>
                openPicker(e.currentTarget, null)
              }
            />
          )}

          {selectedModels.length > 0 && (
            <>
              {canAdd && (
                <Divider
                  orientation="vertical"
                  paddingParallel={2}
                  paddingPerpendicular={2}
                />
              )}
              <div className="flex items-center shrink-0">
                {selectedModels.map((model, index) => {
                  const isAutoModel: boolean =
                    routingEnabled &&
                    model.modelConfigurationId === routingModelId;
                  const ProviderIcon: IconFunctionComponent = isAutoModel
                    ? SvgSparkle
                    : getModelIcon(model.provider, model.modelName);

                  return (
                    <div
                      key={llmOptionKey(model)}
                      className="flex items-center"
                    >
                      {index > 0 && (
                        <Divider
                          orientation="vertical"
                          paddingParallel={2}
                          paddingPerpendicular={2}
                        />
                      )}
                      <SelectButton
                        icon={ProviderIcon}
                        rightIcon={isMultiModel ? SvgX : undefined}
                        state="empty"
                        variant="select-input"
                        size="lg"
                        onClick={(e: React.MouseEvent<HTMLElement>) => {
                          if (isRemoveIcon(e.currentTarget, e.target)) {
                            onRemove(index);
                            return;
                          }
                          openPicker(e.currentTarget, index);
                        }}
                      >
                        {isAutoModel ? t("autoItem.label") : model.displayName}
                      </SelectButton>
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </div>
      </Tooltip>
      <Popover.Anchor virtualRef={anchorRef} />

      <Popover.Content
        side="top"
        align="end"
        width={70}
        onInteractOutside={keepOpenForOpener}
      >
        <ModelSelectorContent
          key={menuKey}
          onSelect={handleSelect}
          isSelected={isSelected}
          isDisabled={isDisabled}
          modelDetail={modelDetail}
        />
      </Popover.Content>
    </Popover>
  );
}
