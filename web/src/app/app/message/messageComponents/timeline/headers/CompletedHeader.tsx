import React from "react";
import { SvgFold, SvgExpand, SvgAddLines, SvgMaximize2 } from "@opal/icons";
import Button from "@/refresh-components/buttons/Button";
import Tag from "@/refresh-components/buttons/Tag";
import Text from "@/refresh-components/texts/Text";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import { Section, LineItemLayout } from "@/layouts/general-layouts";
import { formatDurationSeconds } from "@/lib/time";
import { noProp } from "@/lib/utils";
import IconButton from "@/refresh-components/buttons/IconButton";
import MemoriesModal from "@/refresh-components/modals/MemoriesModal";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";

// =============================================================================
// MemoryTagWithTooltip
// =============================================================================

interface MemoryTagWithTooltipProps {
  memoryText: string | null;
  memoryOperation: "add" | "update" | null;
  memoryId: number | null;
  memoryIndex: number | null;
}

function MemoryTagWithTooltip({
  memoryText,
  memoryOperation,
  memoryId,
  memoryIndex,
}: MemoryTagWithTooltipProps) {
  const memoriesModal = useCreateModal();

  const operationLabel =
    memoryOperation === "add" ? "Added to memories" : "Updated memory";

  const tag = <Tag icon={SvgAddLines} label={operationLabel} />;

  if (!memoryText) return tag;

  return (
    <>
      <memoriesModal.Provider>
        <MemoriesModal
          initialTargetMemoryId={memoryId}
          initialTargetIndex={memoryIndex}
          highlightFirstOnOpen
        />
      </memoriesModal.Provider>
      {memoriesModal.isOpen ? (
        <span>{tag}</span>
      ) : (
        <SimpleTooltip
          delayDuration={0}
          side="bottom"
          className="bg-background-neutral-00 text-text-01 shadow-md max-w-[17.5rem] p-1"
          tooltip={
            <Section flexDirection="column" gap={0.25} height="auto">
              <div className="p-1 w-full">
                <Text as="p" secondaryBody text03>
                  {memoryText}
                </Text>
              </div>
              <LineItemLayout
                variant="mini"
                icon={SvgAddLines}
                title={operationLabel}
                rightChildren={
                  <IconButton
                    small
                    icon={SvgMaximize2}
                    onClick={(e) => {
                      e.stopPropagation();
                      memoriesModal.toggle(true);
                    }}
                  />
                }
              />
            </Section>
          }
        >
          <span>{tag}</span>
        </SimpleTooltip>
      )}
    </>
  );
}

// =============================================================================
// CompletedHeader
// =============================================================================

export interface CompletedHeaderProps {
  totalSteps: number;
  collapsible: boolean;
  isExpanded: boolean;
  onToggle: () => void;
  processingDurationSeconds?: number;
  generatedImageCount?: number;
  isMemoryOnly?: boolean;
  memoryText?: string | null;
  memoryOperation?: "add" | "update" | null;
  memoryId?: number | null;
  memoryIndex?: number | null;
}

/** Header when completed - handles both collapsed and expanded states */
export const CompletedHeader = React.memo(function CompletedHeader({
  totalSteps,
  collapsible,
  isExpanded,
  onToggle,
  processingDurationSeconds = 0,
  generatedImageCount = 0,
  isMemoryOnly = false,
  memoryText = null,
  memoryOperation = null,
  memoryId = null,
  memoryIndex = null,
}: CompletedHeaderProps) {
  if (isMemoryOnly) {
    return (
      <div className="flex w-full justify-between">
        <div className="flex items-center px-[var(--timeline-header-text-padding-x)] py-[var(--timeline-header-text-padding-y)]">
          <MemoryTagWithTooltip
            memoryText={memoryText}
            memoryOperation={memoryOperation}
            memoryId={memoryId}
            memoryIndex={memoryIndex}
          />
        </div>
        {collapsible && totalSteps > 0 && isExpanded && (
          <Button
            size="md"
            tertiary
            onClick={noProp(onToggle)}
            rightIcon={isExpanded ? SvgFold : SvgExpand}
            aria-label="Expand timeline"
            aria-expanded={isExpanded}
          >
            {totalSteps} {totalSteps === 1 ? "step" : "steps"}
          </Button>
        )}
      </div>
    );
  }

  const durationText = processingDurationSeconds
    ? `Thought for ${formatDurationSeconds(processingDurationSeconds)}`
    : "Thought for some time";

  const imageText =
    generatedImageCount > 0
      ? `Generated ${generatedImageCount} ${
          generatedImageCount === 1 ? "image" : "images"
        }`
      : null;

  return (
    <div
      role="button"
      onClick={onToggle}
      className="flex items-center justify-between w-full"
    >
      <div className="flex items-center gap-2 px-[var(--timeline-header-text-padding-x)] py-[var(--timeline-header-text-padding-y)]">
        <Text as="p" mainUiAction text03>
          {isExpanded ? durationText : imageText ?? durationText}
        </Text>
        {memoryOperation && !isExpanded && (
          <MemoryTagWithTooltip
            memoryText={memoryText}
            memoryOperation={memoryOperation}
            memoryId={memoryId}
            memoryIndex={memoryIndex}
          />
        )}
      </div>

      {collapsible && totalSteps > 0 && (
        <Button
          size="md"
          tertiary
          onClick={noProp(onToggle)}
          rightIcon={isExpanded ? SvgFold : SvgExpand}
          aria-label="Expand timeline"
          aria-expanded={isExpanded}
        >
          {totalSteps} {totalSteps === 1 ? "step" : "steps"}
        </Button>
      )}
    </div>
  );
});
