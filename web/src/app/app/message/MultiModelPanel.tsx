"use client";

import { useCallback } from "react";
import { Button } from "@opal/components";
import { Text } from "@opal/components";
import { ContentAction } from "@opal/layouts";
import { SvgChevronLeft, SvgChevronRight, SvgEyeOff, SvgX } from "@opal/icons";
import { getModelIcon } from "@/lib/languageModels";
import AgentMessage, {
  AgentMessageProps,
} from "@/app/app/message/messageComponents/AgentMessage";
import { ErrorBanner } from "@/app/app/message/Resubmit";
import { cn, clickOnKeyDown } from "@opal/utils";
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
  /** Read-only (shared) view: no select/hide controls, header is a static label */
  readOnly?: boolean;
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
  /** Whether a send is in flight, which disables preferred selection */
  selectionDisabled?: boolean;
  /** Narrow-carousel nav to the previous model, flanking the header left */
  carouselPrev?: CarouselNeighbor;
  /** Narrow-carousel nav to the next model, flanking the header right */
  carouselNext?: CarouselNeighbor;
}

export interface CarouselNeighbor {
  provider: string;
  modelName: string;
  displayName: string;
  onClick: () => void;
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
  readOnly = false,
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
  selectionDisabled,
  carouselPrev,
  carouselNext,
}: MultiModelPanelProps) {
  const ModelIcon = getModelIcon(provider, modelName);

  const canSelect =
    !isHidden &&
    !isPreferred &&
    !isGenerating &&
    !selectionDisabled &&
    !readOnly;

  const handlePanelClick = useCallback(() => {
    if (canSelect) onSelect();
  }, [canSelect, onSelect]);

  const headerClassName = cn(
    "rounded-12 transition-colors",
    isPreferred ? "bg-background-tint-02" : "bg-background-tint-00",
    canSelect && "cursor-pointer hover:bg-background-tint-02"
  );

  const headerContent = (
    <>
      <ContentAction
        sizePreset="main-ui"
        variant="body"
        padding={2}
        icon={ModelIcon}
        title={isHidden ? markdown(`~~${displayName}~~`) : displayName}
        rightChildren={
          readOnly ? (
            isPreferred ? (
              <div className="flex items-center px-2">
                <span className="text-action-selection-05 shrink-0">
                  <Text font="secondary-body" color="inherit" nowrap>
                    Preferred Response
                  </Text>
                </span>
              </div>
            ) : undefined
          ) : (
            <div className="flex items-center gap-1 px-2">
              {isPreferred && (
                <>
                  <span className="text-action-selection-05 shrink-0">
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
          )
        }
      />
    </>
  );

  // The header holds its own buttons, so a selectable header stays a div with
  // button semantics rather than a <button> wrapping a <button>.
  const header = canSelect ? (
    <div
      className={headerClassName}
      role="button"
      tabIndex={0}
      aria-label={`Select the ${displayName} response`}
      onKeyDown={clickOnKeyDown(handlePanelClick)}
      onClick={handlePanelClick}
    >
      {headerContent}
    </div>
  ) : (
    <div className={headerClassName}>{headerContent}</div>
  );

  // Narrow-carousel header row: prev/next model nav flanks the model pill.
  const headerWithNav =
    carouselPrev || carouselNext ? (
      // raw-ok: nav row around a flex-1 min-w-0 pill slot, grow semantics no Section width preset can express
      <div className="flex items-center gap-1">
        {carouselPrev ? (
          <Button
            prominence="tertiary"
            icon={getModelIcon(carouselPrev.provider, carouselPrev.modelName)}
            rightIcon={SvgChevronLeft}
            onClick={carouselPrev.onClick}
            tooltip={carouselPrev.displayName}
            aria-label={`Show the ${carouselPrev.displayName} response`}
          />
        ) : null}
        {/* raw-ok: flex-1 slot for the pill inside the nav row, no layout primitive exposes a bare grow wrapper */}
        <div className="flex-1 min-w-0">{header}</div>
        {carouselNext ? (
          <Button
            prominence="tertiary"
            icon={SvgChevronRight}
            rightIcon={getModelIcon(
              carouselNext.provider,
              carouselNext.modelName
            )}
            onClick={carouselNext.onClick}
            tooltip={carouselNext.displayName}
            aria-label={`Show the ${carouselNext.displayName} response`}
          />
        ) : null}
      </div>
    ) : (
      header
    );

  // Hidden/collapsed panel — just the header row
  if (isHidden) {
    return headerWithNav;
  }

  return (
    // raw-ok: panel column, min-w-0 shrink semantics no Section width preset provides
    <div className="flex flex-col gap-3 min-w-0 rounded-16">
      {headerWithNav}
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
