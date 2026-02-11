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

// =============================================================================
// MemoryTagWithTooltip
// =============================================================================

interface MemoryTagWithTooltipProps {
  memoryText: string | null;
  memoryOperation: "add" | "update" | null;
}

function MemoryTagWithTooltip({
  memoryText,
  memoryOperation,
}: MemoryTagWithTooltipProps) {
  const operationLabel =
    memoryOperation === "add" ? "Added to memories" : "Updated memory";

  const tag = <Tag icon={SvgAddLines} label={operationLabel} />;

  if (!memoryText) return tag;

  return (
    <SimpleTooltip
      side="bottom"
      className="bg-background-neutral-00 text-text-01 shadow-md max-w-[17.5rem] p-1"
      tooltip={
        <Section flexDirection="column" gap={0.25} height="auto">
          <div className="p-1">
            <Text as="p" secondaryBody text03>
              {memoryText}
            </Text>
          </div>
          <LineItemLayout
            variant="mini"
            icon={SvgAddLines}
            title={operationLabel}
            rightChildren={<IconButton small icon={SvgMaximize2} />}
          />
        </Section>
      }
    >
      <span>{tag}</span>
    </SimpleTooltip>
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
}: CompletedHeaderProps) {
  if (isMemoryOnly) {
    return (
      <div className="flex items-center w-full px-[var(--timeline-header-text-padding-x)] py-[var(--timeline-header-text-padding-y)]">
        <MemoryTagWithTooltip
          memoryText={memoryText}
          memoryOperation={memoryOperation}
        />
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
