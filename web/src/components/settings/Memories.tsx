"use client";

import FileTile from "@/refresh-components/tiles/FileTile";
import ButtonTile from "@/refresh-components/tiles/ButtonTile";
import { SvgAddLines, SvgFilter, SvgMenu, SvgPlusCircle } from "@opal/icons";
import MemoriesModal from "@/refresh-components/modals/MemoriesModal";
import LineItem from "@/refresh-components/buttons/LineItem";
import IconButton from "@/refresh-components/buttons/IconButton";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";

interface MemoriesProps {
  memories: string[];
  onSaveMemories: (memories: string[]) => Promise<boolean>;
}

export default function Memories({ memories, onSaveMemories }: MemoriesProps) {
  const memoriesModal = useCreateModal();

  return (
    <>
      {memories.length === 0 ? (
        <LineItem
          skeleton
          description="Add personal note or memory that Onyx should remember."
          onClick={() => memoriesModal.toggle(true)}
          rightChildren={
            <IconButton
              internal
              icon={SvgPlusCircle}
              onClick={() => memoriesModal.toggle(true)}
            />
          }
        />
      ) : (
        <div className="flex flex-row flex-wrap items-center gap-2">
          {memories.map((memory, index) => (
            <FileTile key={index} description={memory} />
          ))}
          <ButtonTile
            title="View/Add"
            description="All notes"
            icon={SvgAddLines}
            onClick={() => memoriesModal.toggle(true)}
          />
        </div>
      )}

      <memoriesModal.Provider>
        <MemoriesModal memories={memories} onSaveMemories={onSaveMemories} />
      </memoriesModal.Provider>
    </>
  );
}
