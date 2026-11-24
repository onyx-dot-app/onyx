"use client";

import { useTranslations } from "next-intl";
import { SvgAddLines, SvgMaximize2 } from "@opal/icons";
import { Button, Text } from "@opal/components";
import Tag from "@/refresh-components/buttons/Tag";
import { Tooltip } from "@opal/components";
import { ContentAction, Section } from "@opal/layouts";
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
