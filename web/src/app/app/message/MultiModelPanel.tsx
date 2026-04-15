"use client";

import { useCallback } from "react";
import { Button } from "@opal/components";
import { Text } from "@opal/components";
import { ContentAction } from "@opal/layouts";
import { SvgEyeOff, SvgX } from "@opal/icons";
import { getModelIcon } from "@/lib/llmConfig";
import AgentMessage, {
  AgentMessageProps,
} from "@/app/app/message/messageComponents/AgentMessage";
import { ErrorBanner } from "@/app/app/message/Resubmit";
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
  /** Callback to deselect this panel as preferred */
  onDeselect?: () => void;
  /** Callback to hide/show this panel */
  onToggleVisibility: () => void;
  /** Props to pass through to AgentMessage */
  agentMessageProps: AgentMessageProps;
  /** Error message when this model failed */
  errorMessage?: string | null;
  /** Error code for display */
  errorCode?: string | null;
  /** Whether the error is retryable */
  isRetryable?: boolean;
  /** Stack trace for debugging */
  errorStackTrace?: string | null;
  /** Additional error details */
  errorDetails?: Record<string, any> | null;
  /** Whether any model is still streaming — disables preferred selection */
  isGenerating?: boolean;
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
  onDeselect,
  onToggleVisibility,
  agentMessageProps,
  errorMessage,
  errorCode,
  isRetryable,
  errorStackTrace,
  errorDetails,
  isGenerating,
}: MultiModelPanelProps) {
  const ModelIcon = getModelIcon(provider, modelName);

  const canSelect = !isHidden && !isPreferred && !isGenerating;

  const handlePanelClick = useCallback(() => {
    if (canSelect) onSelect();
  }, [canSelect, onSelect]);

  const header = (
    <div
      className={cn(
        "rounded-12 transition-colors",
        isPreferred ? "bg-background-tint-02" : "bg-background-tint-00",
        canSelect && "cursor-pointer hover:bg-background-tint-02"
      )}
      onClick={handlePanelClick}
    >
      <ContentAction
        sizePreset="main-ui"
        variant="body"
        paddingVariant="lg"
        icon={ModelIcon}
        title={isHidden ? markdown(`~~${displayName}~~`) : displayName}
        rightChildren={
          <div className="flex items-center gap-1 px-2">
            {isPreferred && (
              <>
                <span className="text-action-link-05 shrink-0">
                  <Text font="secondary-body" color="inherit" nowrap>
                    Preferred Response
                  </Text>
                </span>
                {onDeselect && (
                  <Button
                    prominence="tertiary"
                    icon={SvgX}
                    size="sm"
                    onClick={(e) => {
                      e.stopPropagation();
                      onDeselect();
                    }}
                    tooltip="Deselect preferred response"
                  />
                )}
              </>
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
    <div className="flex flex-col gap-3 min-w-0 rounded-16">
      {header}
      {errorMessage ? (
        <div className="p-4">
          <ErrorBanner
            error={errorMessage}
            errorCode={errorCode || undefined}
            isRetryable={isRetryable ?? true}
            details={errorDetails || undefined}
            stackTrace={errorStackTrace}
          />
        </div>
      ) : (
        <div className={cn(isNonPreferredInSelection && "pointer-events-none")}>
          <AgentMessage
            {...agentMessageProps}
            hideFooter={isNonPreferredInSelection}
            disableTTS
          />
        </div>
      )}
    </div>
  );
}
