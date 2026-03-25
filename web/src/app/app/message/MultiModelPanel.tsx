"use client";

import { useCallback } from "react";
import { Button } from "@opal/components";
import { Hoverable } from "@opal/core";
import { SvgEyeClosed, SvgMoreHorizontal, SvgX } from "@opal/icons";
import Text from "@/refresh-components/texts/Text";
import { getProviderIcon } from "@/app/admin/configuration/llm/utils";
import AgentMessage, {
  AgentMessageProps,
} from "@/app/app/message/messageComponents/AgentMessage";
import { cn } from "@/lib/utils";

export interface MultiModelPanelProps {
  /** Index of this model in the selectedModels array (used for Hoverable group key) */
  modelIndex: number;
  /** Provider name for icon lookup */
  provider: string;
  /** Model name for icon lookup and display */
  modelName: string;
  /** Display-friendly model name */
  displayName: string;
  /** Whether this panel is the preferred/selected response */
  isPreferred: boolean;
  /** Whether this panel is currently hidden */
  isHidden: boolean;
  /** Whether this is a non-preferred panel in selection mode (pushed off-screen) */
  isNonPreferredInSelection: boolean;
  /** Callback when user clicks this panel to select as preferred */
  onSelect: () => void;
  /** Callback to hide/show this panel */
  onToggleVisibility: () => void;
  /** Props to pass through to AgentMessage */
  agentMessageProps: AgentMessageProps;
}

export default function MultiModelPanel({
  modelIndex,
  provider,
  modelName,
  displayName,
  isPreferred,
  isHidden,
  isNonPreferredInSelection,
  onSelect,
  onToggleVisibility,
  agentMessageProps,
}: MultiModelPanelProps) {
  const ProviderIcon = getProviderIcon(provider, modelName);

  const handlePanelClick = useCallback(() => {
    if (!isHidden) {
      onSelect();
    }
  }, [isHidden, onSelect]);

  // Hidden/collapsed panel — compact strip: icon + strikethrough name + eye icon
  if (isHidden) {
    return (
      <div className="flex items-center gap-1.5 rounded-08 bg-background-tint-00 px-2 py-1 opacity-50">
        <div className="flex items-center justify-center size-5 shrink-0">
          <ProviderIcon size={16} />
        </div>
        <Text secondaryBody text02 nowrap className="line-through">
          {displayName}
        </Text>
        <Button
          prominence="tertiary"
          icon={SvgEyeClosed}
          size="2xs"
          onClick={onToggleVisibility}
          tooltip="Show response"
        />
      </div>
    );
  }

  const hoverGroup = `panel-${modelIndex}`;

  return (
    <Hoverable.Root group={hoverGroup}>
      <div
        className="flex flex-col min-w-0 gap-3 cursor-pointer"
        onClick={handlePanelClick}
      >
        {/* Panel header */}
        <div
          className={cn(
            "flex items-center gap-1.5 rounded-12 px-2 py-1",
            isPreferred ? "bg-background-tint-02" : "bg-background-tint-00"
          )}
        >
          <div className="flex items-center justify-center size-5 shrink-0">
            <ProviderIcon size={16} />
          </div>
          <Text mainUiAction text04 nowrap className="flex-1 min-w-0 truncate">
            {displayName}
          </Text>
          {isPreferred && (
            <Text secondaryBody nowrap className="text-action-link-05 shrink-0">
              Preferred Response
            </Text>
          )}
          <Button
            prominence="tertiary"
            icon={SvgMoreHorizontal}
            size="2xs"
            tooltip="More"
            onClick={(e) => e.stopPropagation()}
          />
          <Button
            prominence="tertiary"
            icon={SvgX}
            size="2xs"
            onClick={(e) => {
              e.stopPropagation();
              onToggleVisibility();
            }}
            tooltip="Hide response"
          />
        </div>

        {/* "Select This Response" hover affordance */}
        {!isPreferred && !isNonPreferredInSelection && (
          <Hoverable.Item group={hoverGroup} variant="opacity-on-hover">
            <div className="flex justify-center pointer-events-none">
              <div className="flex items-center h-6 bg-background-tint-00 rounded-08 px-1 shadow-sm">
                <Text
                  secondaryBody
                  className="font-semibold text-text-03 px-1 whitespace-nowrap"
                >
                  Select This Response
                </Text>
              </div>
            </div>
          </Hoverable.Item>
        )}

        {/* Response body */}
        <div className={cn(isNonPreferredInSelection && "pointer-events-none")}>
          <AgentMessage
            {...agentMessageProps}
            hideFooter={isNonPreferredInSelection}
          />
        </div>
      </div>
    </Hoverable.Root>
  );
}
