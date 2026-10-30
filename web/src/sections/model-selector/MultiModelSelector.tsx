"use client";

import { useState, useMemo, useRef, type RefObject } from "react";
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
  const [detailKey, setDetailKey] = useState<string | null>(null);
  const rowRef = useRef<HTMLDivElement>(null);
  const addButtonRef = useRef<HTMLElement>(null);
  const pillRefs = useRef(new Map<string, HTMLElement>());
  // Radix reports an outside pointerdown only on the following click, by which
  // time a pill x has unmounted its target, so the row's last one is kept.
  const rowPointerDownRef = useRef<PointerEvent | null>(null);
  // A removed pill's last rect, so the closing popover does not jump during its
  // exit animation. Keyed so it never applies to another model's pane.
  const lastPillRef = useRef<{ key: string; rect: DOMRect } | null>(null);

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
  // With multi-model off an add is impossible, so a row click switches the sole model.
  const canReplace: boolean = !multiModelAllowed && selectedModels.length === 1;

  // Container-level tooltip carries only the disabled reason. The add button
  // labels itself, so an enabled row shows no tooltip outside the button.
  const selectorTooltip = noModelsToSelect
    ? t("multiModel.noModels.tooltip")
    : undefined;

  const selectedKeys = useMemo(
    () => new Set(selectedModels.map(llmOptionKey)),
    [selectedModels]
  );

  const isSelected = (option: LLMOption) =>
    selectedKeys.has(llmOptionKey(option));

  const isDisabled = (option: LLMOption) =>
    !isSelected(option) && !canAdd && !canReplace;

  // The list sits on +, or on the row while + is hidden; a change re-anchors.
  const listOnAdd: boolean = detailKey === null && canAdd;

  // Resolved at measure time so a pane follows its model's pill as other pills
  // come and go. A new object per target makes Radix re-anchor and move the
  // observers. An unselected model's pane has no pill and shares the list's place.
  const anchorRef = useMemo<RefObject<PopoverAnchor>>(() => {
    const pill = (): HTMLElement | undefined =>
      detailKey === null ? undefined : pillRefs.current.get(detailKey);
    const listElement = (): HTMLElement | undefined =>
      addButtonRef.current ?? rowRef.current ?? undefined;
    return {
      current: {
        getBoundingClientRect: () => {
          const element = pill();
          if (detailKey !== null && element) {
            const rect: DOMRect = element.getBoundingClientRect();
            lastPillRef.current = { key: detailKey, rect };
            return rect;
          }
          const held: DOMRect | null =
            lastPillRef.current?.key === detailKey
              ? lastPillRef.current.rect
              : null;
          return (
            held ?? listElement()?.getBoundingClientRect() ?? new DOMRect()
          );
        },
        get contextElement() {
          return pill() ?? listElement();
        },
      },
    };
  }, [detailKey, listOnAdd]);

  const toSelectedModel = (option: LLMOption): SelectedModel => ({
    name: option.name,
    provider: option.provider,
    modelName: option.modelName,
    modelConfigurationId: option.modelConfigurationId ?? null,
    displayName: option.displayName,
  });

  // The pane of a removed model has no pill left to sit on, so the menu closes.
  const removeAt = (index: number) => {
    const removed: SelectedModel | undefined = selectedModels[index];
    onRemove(index);
    if (removed && llmOptionKey(removed) === detailKey) setOpen(false);
  };

  const handleSelect = (option: LLMOption) => {
    const key = llmOptionKey(option);
    const existingIndex = selectedModels.findIndex(
      (m) => llmOptionKey(m) === key
    );
    if (existingIndex >= 0) {
      // The sole model stays: single-model chat always needs one.
      if (isMultiModel) removeAt(existingIndex);
      return;
    }
    if (canReplace) {
      onReplace(0, toSelectedModel(option));
      return;
    }
    if (canAdd) onAdd(toSelectedModel(option));
  };

  // Every opener sets the pane key (null without a pane), so a close keeps it
  // and the anchor holds through the exit animation.
  const openPicker = (modelKey: string | null) => {
    // `pointer-events-none` only blocks the mouse; guard the keyboard path too.
    if (noModelsToSelect) return;
    setDetailKey(modelDetail ? modelKey : null);
    setOpen(true);
  };

  // The row has no Popover.Trigger, so its +, pills and x need the trigger's
  // exemption from dismissal.
  const keepOpenOnRowEvent = (event: CustomEvent<{ originalEvent: Event }>) => {
    const fromRowPointerDown: boolean =
      event.detail.originalEvent === rowPointerDownRef.current;
    if (fromRowPointerDown) rowPointerDownRef.current = null;
    const fromRow: boolean =
      fromRowPointerDown ||
      (event.target instanceof Node &&
        !!rowRef.current?.contains(event.target));
    if (fromRow) event.preventDefault();
  };

  const isRemoveIconEvent = (e: React.SyntheticEvent): boolean => {
    if (!isMultiModel) return false;
    const icons = e.currentTarget.querySelectorAll(
      ".interactive-foreground-icon"
    );
    const lastIcon = icons[icons.length - 1];
    return (
      !!lastIcon && e.target instanceof Node && lastIcon.contains(e.target)
    );
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      {/* Disabled state blocks pointer events on children only, so the
          container stays hoverable and this Tooltip can surface the reason. */}
      <Tooltip tooltip={selectorTooltip} side="top">
        <div
          ref={rowRef}
          data-testid="model-selector"
          onPointerDownCapture={(e) => {
            rowPointerDownRef.current = e.nativeEvent;
          }}
          aria-disabled={noModelsToSelect || undefined}
          className={cn(
            "flex items-center justify-end gap-1 p-1",
            noModelsToSelect &&
              "cursor-not-allowed select-none opacity-50 [&>*]:pointer-events-none"
          )}
        >
          {canAdd && (
            <Button
              ref={addButtonRef}
              prominence="tertiary"
              icon={SvgPlusCircle}
              size="sm"
              tooltip={t("multiModel.addModelButton.label")}
              aria-label={t("multiModel.addModelButton.label")}
              onClick={() => openPicker(null)}
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

                  const modelKey: string = llmOptionKey(model);

                  return (
                    <div key={modelKey} className="flex items-center">
                      {index > 0 && (
                        <Divider
                          orientation="vertical"
                          paddingParallel={2}
                          paddingPerpendicular={2}
                        />
                      )}
                      <SelectButton
                        ref={(node: HTMLElement | null) => {
                          if (!node) return;
                          pillRefs.current.set(modelKey, node);
                          return () => {
                            pillRefs.current.delete(modelKey);
                          };
                        }}
                        icon={ProviderIcon}
                        rightIcon={isMultiModel ? SvgX : undefined}
                        state="empty"
                        variant="select-input"
                        size="lg"
                        onClick={(e: React.MouseEvent<HTMLElement>) => {
                          if (isRemoveIconEvent(e)) {
                            removeAt(index);
                            return;
                          }
                          openPicker(modelKey);
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
        onInteractOutside={keepOpenOnRowEvent}
      >
        <ModelSelectorContent
          onSelect={handleSelect}
          isSelected={isSelected}
          isDisabled={isDisabled}
          modelDetail={modelDetail}
          detailKey={detailKey}
          onDetailKeyChange={setDetailKey}
        />
      </Popover.Content>
    </Popover>
  );
}
