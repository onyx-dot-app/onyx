"use client";

import { useCallback } from "react";
import { Button } from "@opal/components";
import { Text } from "@opal/components";
import { ContentAction } from "@opal/layouts";
import { SvgEyeOff, SvgX } from "@opal/icons";
import { getProviderIcon } from "@/app/admin/configuration/llm/utils";
import AgentMessage, {
  AgentMessageProps,
} from "@/app/app/message/messageComponents/AgentMessage";
import { cn } from "@/lib/utils";
import { markdown } from "@opal/utils";

export interface MultiModelPanelProps {
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

/**
 * A single model's response panel within the multi-model view.
 *
 * Renders in two states:
 * - **Hidden** — compact header strip only (provider icon + strikethrough name + show button).
 * - **Visible** — full header plus `AgentMessage` body. Clicking anywhere on a
 *   visible non-preferred panel marks it as preferred.
 *
 * The `isNonPreferredInSelection` flag disables pointer events on the body and
 * hides the footer so the panel acts as a passive comparison surface.
 */
export default function MultiModelPanel({
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
    if (!isHidden && !isPreferred) onSelect();
  }, [isHidden, isPreferred, onSelect]);

  const header = (
    <div
      className={cn(
        "rounded-12",
        isPreferred ? "bg-background-tint-02" : "bg-background-tint-00"
      )}
    >
      <ContentAction
        sizePreset="main-ui"
        variant="body"
        paddingVariant="lg"
        icon={ProviderIcon}
        title={isHidden ? markdown(`~~${displayName}~~`) : displayName}
        rightChildren={
          <div className="flex items-center gap-1 px-2">
            {isPreferred && (
              <span className="text-action-link-05 shrink-0">
                <Text font="secondary-body" color="inherit" nowrap>
                  Preferred Response
                </Text>
              </span>
            )}
            {!isPreferred && (
              <Button
                prominence="tertiary"
                icon={isHidden ? SvgEyeOff : SvgX}
                size="md"
                onClick={(e) => {
                  e.stopPropagation();
                  onToggleVisibility();
                }}
                tooltip={isHidden ? "Show response" : "Hide response"}
              />
            )}
          </div>
        }
      />
    </div>
  );

  // Hidden/collapsed panel — just the header row
  if (isHidden) {
    return header;
  }

  return (
    <div
      className={cn(
        "flex flex-col gap-3 min-w-0 rounded-16 transition-colors",
        !isPreferred && "cursor-pointer hover:bg-background-tint-02"
      )}
      onClick={handlePanelClick}
    >
      {header}
      <div className={cn(isNonPreferredInSelection && "pointer-events-none")}>
        <AgentMessage
          {...agentMessageProps}
          hideFooter={isNonPreferredInSelection}
        />
      </div>
    </div>
  );
}
