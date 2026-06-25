"use client";

import { useState } from "react";
import FileTile from "@/refresh-components/tiles/FileTile";
import ButtonTile from "@/refresh-components/tiles/ButtonTile";
import { SvgAddLines, SvgFilter, SvgMenu, SvgPlusCircle } from "@opal/icons";
import MemoriesModal from "@/refresh-components/modals/MemoriesModal";
import LineItem from "@/refresh-components/buttons/LineItem";
import { Button } from "@opal/components";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import { MemoryItem } from "@/lib/types";
import { useTranslation } from "react-i18next";

interface MemoriesProps {
  memories: MemoryItem[];
  onSaveMemories: (memories: MemoryItem[]) => Promise<boolean>;
}

export default function Memories({ memories, onSaveMemories }: MemoriesProps) {
  const memoriesModal = useCreateModal();
  const [targetMemoryId, setTargetMemoryId] = useState<number | null>(null);
  const { t } = useTranslation();

  return (
    <>
      {memories.length === 0 ? (
        <LineItem
          skeleton
          description={t("settings.chats.add_note_placeholder", "Add personal note or memory that Onyx should remember.")}
          onClick={() => {
            setTargetMemoryId(null);
            memoriesModal.toggle(true);
          }}
          rightChildren={
            <Button
              prominence="internal"
              icon={SvgPlusCircle}
              onClick={() => {
                setTargetMemoryId(null);
                memoriesModal.toggle(true);
              }}
            />
          }
        />
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
            title={t("settings.chats.view_add", "View/Add")}
            description={t("settings.chats.all_memories", "All Memories")}
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
