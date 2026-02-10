"use client";

import { useState } from "react";
import Text from "@/refresh-components/texts/Text";
import Tile from "@/refresh-components/tiles/Tile";
import { SvgFilter, SvgMenu, SvgPlusCircle } from "@opal/icons";
import { Interactive } from "@opal/core";
import { Card } from "@/refresh-components/cards";
import MemoriesModal from "@/refresh-components/modals/MemoriesModal";

interface MemoriesProps {
  memories: string[];
  onSaveMemories: (memories: string[]) => Promise<boolean>;
}

export default function Memories({ memories, onSaveMemories }: MemoriesProps) {
  const [showModal, setShowModal] = useState(false);

  return (
    <>
      {memories.length === 0 ? (
        <Interactive.Base
          variant="default"
          subvariant="ghost"
          onClick={() => setShowModal(true)}
        >
          <Card
            variant="tertiary"
            className="rounded-08"
            padding={0.5}
            flexDirection="row"
            justifyContent="between"
          >
            <Text secondaryBody text03>
              Add personal note or memory that Onyx should remember.
            </Text>
            <SvgPlusCircle className="stroke-text-02" size={16} />
          </Card>
        </Interactive.Base>
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
