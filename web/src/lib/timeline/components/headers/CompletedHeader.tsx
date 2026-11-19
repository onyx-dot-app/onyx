"use client";

import { useTranslations } from "next-intl";
import { SvgAddLines, SvgMaximize2 } from "@opal/icons";
import { Button, Presence, Text } from "@opal/components";
import Tag from "@/refresh-components/buttons/Tag";
import { Tooltip } from "@opal/components";
import { ContentAction, Section } from "@opal/layouts";
import { formatDurationSeconds } from "@opal/time";
import MemoriesModal from "@/refresh-components/modals/MemoriesModal";
import { useCreateModal } from "@opal/components";

// =============================================================================
// MemoryTagWithTooltip
// =============================================================================

interface MemoryTagWithTooltipProps {
  memoryText: string | null;
  memoryOperation: "add" | "update" | null;
  memoryId: number | null;
  memoryIndex: number | null;
}

export function MemoryTagWithTooltip({
  memoryText,
  memoryOperation,
  memoryId,
  memoryIndex,
}: MemoryTagWithTooltipProps) {
  const t = useTranslations("chat.messages.timeline");
  const memoriesModal = useCreateModal();

  const operationLabel =
    memoryOperation === "add"
      ? t("memoryTag.added.label")
      : t("memoryTag.updated.label");

  const tag = <Tag icon={SvgAddLines} label={operationLabel} />;

  if (!memoryText) return tag;

  return (
    <>
      <memoriesModal.Provider>
        <MemoriesModal
          initialTargetMemoryId={memoryId}
          initialTargetIndex={memoryIndex}
          highlightOnOpen
        />
      </memoriesModal.Provider>
      {memoriesModal.isOpen ? (
        <span>{tag}</span>
      ) : (
        <Tooltip
          delayDuration={0}
          side="bottom"
          tooltip={
            <Section
              flexDirection="column"
              alignItems="start"
              padding={1}
              gap={1}
              height="auto"
            >
              <div className="p-1">
                <Text as="p" font="secondary-body" color="text-03">
                  {memoryText}
                </Text>
              </div>
              <ContentAction
                font="secondary-body"
                icon={SvgAddLines}
                title={operationLabel}
                padding={1}
                titleColor="text-03"
                rightChildren={
                  <Button
                    prominence="tertiary"
                    size="sm"
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
        </Tooltip>
      )}
    </>
  );
}

// =============================================================================
// CompletedHeader
// =============================================================================

export interface CompletedHeaderProps {
  /** The run is open: the duration shows instead of the image count. */
  isExpanded: boolean;
  processingDurationSeconds?: number;
  generatedImageCount?: number;
  isMemoryOnly?: boolean;
  memoryText?: string | null;
  memoryOperation?: "add" | "update" | null;
  memoryId?: number | null;
  memoryIndex?: number | null;
}

/** The finished run's title: how long it took, or what it produced. */
export function CompletedHeader({
  isExpanded,
  processingDurationSeconds = 0,
  generatedImageCount = 0,
  isMemoryOnly = false,
  memoryText = null,
  memoryOperation = null,
  memoryId = null,
  memoryIndex = null,
}: CompletedHeaderProps) {
  const t = useTranslations("chat.messages.timeline");

  if (isMemoryOnly) {
    return (
      <Section
        flexDirection="row"
        justifyContent="start"
        gap={0}
        height="fit"
        className="flex-1 min-w-0 mx-(--timeline-header-text-padding-x) my-(--timeline-header-text-padding-y)"
      >
        <MemoryTagWithTooltip
          memoryText={memoryText}
          memoryOperation={memoryOperation}
          memoryId={memoryId}
          memoryIndex={memoryIndex}
        />
      </Section>
    );
  }

  const durationText = processingDurationSeconds
    ? t("thoughtDuration.label", {
        duration: formatDurationSeconds(processingDurationSeconds),
      })
    : t("thoughtUnknownDuration.label");

  const imageText =
    generatedImageCount > 0
      ? t("generatedImages.label", { count: generatedImageCount })
      : null;

  const shownText = isExpanded ? durationText : (imageText ?? durationText);

  // The summary swaps through Presence.Swap whenever its text changes
  // (opening the card shows the duration in place of the image count). A
  // saved memory's tag sits on the card's right side (see RunCard), so it
  // never swaps the summary.
  return (
    <Presence.Swap swapKey={shownText}>
      <Section
        flexDirection="row"
        justifyContent="start"
        gap={0}
        height="fit"
        className="flex-1 min-w-0 mx-(--timeline-header-text-padding-x) my-(--timeline-header-text-padding-y)"
      >
        <Text as="p" font="main-ui-action" color="text-03">
          {shownText}
        </Text>
      </Section>
    </Presence.Swap>
  );
}
