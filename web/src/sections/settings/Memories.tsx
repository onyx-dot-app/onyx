"use client";

import { useState } from "react";
import FileTile from "@/refresh-components/tiles/FileTile";
import ButtonTile from "@/refresh-components/tiles/ButtonTile";
import { SvgAddLines, SvgFilter, SvgMenu, SvgPlusCircle } from "@opal/icons";
import MemoriesModal from "@/refresh-components/modals/MemoriesModal";
import LineItem from "@/refresh-components/buttons/LineItem";
import IconButton from "@/refresh-components/buttons/IconButton";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import { MemoryItem } from "@/lib/types";

interface MemoriesProps {
  memories: MemoryItem[];
  onSaveMemories: (memories: MemoryItem[]) => Promise<boolean>;
}

export default function Memories({ memories, onSaveMemories }: MemoriesProps) {
  const memoriesModal = useCreateModal();
  const [targetMemoryId, setTargetMemoryId] = useState<number | null>(null);

  return (
    <>
      {memories.length === 0 ? (
        <LineItem
          skeleton
          description="Add personal note or memory that Onyx should remember."
          onClick={() => {
            setTargetMemoryId(null);
            memoriesModal.toggle(true);
          }}
          rightChildren={
            <IconButton
              internal
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
            title="View/Add"
            description="All Memories"
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
        />
      </memoriesModal.Provider>
    </>
  );
}
