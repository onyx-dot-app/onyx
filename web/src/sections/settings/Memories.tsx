"use client";

import { useState } from "react";
import { SvgAddLines, SvgPlusCircle } from "@opal/icons";
import { Button, SelectCard, Text, useCreateModal } from "@opal/components";
import { Section } from "@opal/layouts";
import { useTranslations } from "next-intl";
import FileTile from "@/refresh-components/tiles/FileTile";
import ButtonTile from "@/refresh-components/tiles/ButtonTile";
import MemoriesModal from "@/refresh-components/modals/MemoriesModal";
import { MemoryItem } from "@/lib/types";

interface MemoriesProps {
  memories: MemoryItem[];
  onSaveMemories: (memories: MemoryItem[]) => Promise<boolean>;
}

export default function Memories({ memories, onSaveMemories }: MemoriesProps) {
  const t = useTranslations("settings.memory");
  const memoriesModal = useCreateModal();
  const [targetMemoryId, setTargetMemoryId] = useState<number | null>(null);

  return (
    <>
      {memories.length === 0 ? (
        // A call-to-action, not a list row: the legacy LineItem "skeleton"
        // dressed this as a placeholder, but it is a clickable card that
        // opens the add-memory modal. The dashed border keeps the
        // "nothing here yet" reading.
        <SelectCard
          border="dashed"
          padding={2}
          rounding={3}
          // Keep the card visually engaged while the modal it opened is up —
          // the same treatment OpenButton and Divider give their popovers.
          interaction={memoriesModal.isOpen ? "hover" : "rest"}
          onClick={() => {
            setTargetMemoryId(null);
            memoriesModal.toggle(true);
          }}
        >
          <Section flexDirection="row" gap={1} justifyContent="between">
            <Section padding={1} width="full" alignItems="start">
              <Text font="secondary-body" color="text-03">
                {t("empty.description")}
              </Text>
            </Section>
            <Button
              prominence="tertiary"
              icon={SvgPlusCircle}
              size="md"
              aria-label={t("empty.addButton.ariaLabel")}
              onClick={(event) => {
                // The card underneath opens the same modal; without this the
                // click runs both handlers and relies on them staying
                // identical.
                event.stopPropagation();
                setTargetMemoryId(null);
                memoriesModal.toggle(true);
              }}
            />
          </Section>
        </SelectCard>
      ) : (
        <div className="self-stretch flex flex-row items-center justify-between gap-2">
          <div className="flex flex-row items-center gap-2">
            {memories.slice(0, 2).map((memory, index) => (
              <FileTile
                key={memory.id ?? index}
                description={memory.content}
                onOpen={() => {
                  setTargetMemoryId(memory.id);
                  memoriesModal.toggle(true);
                }}
              />
            ))}
          </div>
          <ButtonTile
            title={t("viewAll.title")}
            description={t("viewAll.description")}
            icon={SvgAddLines}
            onClick={() => {
              setTargetMemoryId(null);
              memoriesModal.toggle(true);
            }}
          />
        </div>
      )}

      <memoriesModal.Provider>
        <MemoriesModal
          memories={memories}
          onSaveMemories={onSaveMemories}
          initialTargetMemoryId={targetMemoryId}
          focusNewLine={targetMemoryId === null}
        />
      </memoriesModal.Provider>
    </>
  );
}
