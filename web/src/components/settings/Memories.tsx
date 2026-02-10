"use client";

import { useState } from "react";
import Tile from "@/refresh-components/tiles/Tile";
import { SvgFilter, SvgMenu, SvgPlusCircle } from "@opal/icons";
import MemoriesModal from "@/refresh-components/modals/MemoriesModal";
import LineItem from "@/refresh-components/buttons/LineItem";
import { Icon } from "lucide-react";
import IconButton from "@/refresh-components/buttons/IconButton";

interface MemoriesProps {
  memories: string[];
  onSaveMemories: (memories: string[]) => Promise<boolean>;
}

export default function Memories({ memories, onSaveMemories }: MemoriesProps) {
  const [showModal, setShowModal] = useState(false);

  return (
    <>
      {memories.length === 0 ? (
        <LineItem
          skeleton
          description="Add personal note or memory that Onyx should remember."
          onClick={() => setShowModal(true)}
          rightChildren={
            <IconButton
              internal
              icon={SvgPlusCircle}
              onClick={() => setShowModal(true)}
            />
          }
        />
      ) : (
        <div className="flex flex-row flex-wrap items-center gap-2">
          {memories.map((memory, index) => (
            <Tile key={index} type="file" icon={SvgMenu} description={memory} />
          ))}
          <Tile
            type="button"
            title="View/Add"
            description="All notes"
            icon={SvgFilter}
            onClick={() => setShowModal(true)}
          />
        </div>
      )}

      {showModal && (
        <MemoriesModal
          memories={memories}
          onSaveMemories={onSaveMemories}
          onClose={() => setShowModal(false)}
        />
      )}
    </>
  );
}
