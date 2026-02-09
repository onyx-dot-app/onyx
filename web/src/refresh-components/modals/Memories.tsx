"use client";

import { useRef, useCallback, useEffect, useState } from "react";
import Modal from "@/refresh-components/Modal";
import { Section } from "@/layouts/general-layouts";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import InputTextArea from "@/refresh-components/inputs/InputTextArea";
import CreateButton from "@/refresh-components/buttons/CreateButton";
import IconButton from "@/refresh-components/buttons/IconButton";
import Text from "@/refresh-components/texts/Text";
import Tile from "@/refresh-components/tiles/Tile";
import { usePopup } from "@/components/admin/connectors/Popup";
import {
  SvgAddLines,
  SvgFilter,
  SvgMenu,
  SvgMinusCircle,
  SvgPlusCircle,
} from "@opal/icons";
import { Card } from "../cards";
import Button from "../buttons/Button";

interface LocalMemory {
  id: number;
  content: string;
  isNew: boolean;
}

interface MemoriesProps {
  memories: string[];
  onSaveMemories: (memories: string[]) => Promise<boolean>;
}

const MAX_MEMORY_LENGTH = 200;

export default function Memories({ memories, onSaveMemories }: MemoriesProps) {
  const [showModal, setShowModal] = useState(false);

  return (
    <>
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

interface MemoriesModalProps {
  memories: string[];
  onSaveMemories: (memories: string[]) => Promise<boolean>;
  onClose: () => void;
}

function MemoriesModal({
  memories,
  onSaveMemories,
  onClose,
}: MemoriesModalProps) {
  const { popup, setPopup } = usePopup();
  const [localMemories, setLocalMemories] = useState<LocalMemory[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const initialMemoriesRef = useRef<string[]>([]);

  // Initialize local memories from props
  useEffect(() => {
    const existingMemories: LocalMemory[] = memories.map((content, index) => ({
      id: index + 1,
      content,
      isNew: false,
    }));

    setLocalMemories(existingMemories);
    initialMemoriesRef.current = memories;
  }, [memories]);

  const handleAddMemory = useCallback(() => {
    setLocalMemories((prev) => [
      ...prev,
      { id: Date.now(), content: "", isNew: true },
    ]);
  }, []);

  const handleUpdateMemory = useCallback((index: number, value: string) => {
    setLocalMemories((prev) =>
      prev.map((memory, i) =>
        i === index ? { ...memory, content: value } : memory
      )
    );
  }, []);

  const handleRemoveMemory = useCallback(
    async (index: number) => {
      const memory = localMemories[index];
      if (!memory) return;

      if (memory.isNew) {
        setLocalMemories((prev) => prev.filter((_, i) => i !== index));
        return;
      }

      const newMemories = localMemories
        .filter((_, i) => i !== index)
        .filter((m) => !m.isNew || m.content.trim())
        .map((m) => m.content);

      const success = await onSaveMemories(newMemories);
      if (success) {
        setPopup({ message: "Memory deleted", type: "success" });
      } else {
        setPopup({ message: "Failed to delete memory", type: "error" });
      }
    },
    [localMemories, onSaveMemories, setPopup]
  );

  const handleBlurMemory = useCallback(
    async (index: number) => {
      const memory = localMemories[index];
      if (!memory || !memory.content.trim()) return;

      const newMemories = localMemories
        .filter((m) => m.content.trim())
        .map((m) => m.content);

      const memoriesChanged =
        JSON.stringify(newMemories) !==
        JSON.stringify(initialMemoriesRef.current);

      if (!memoriesChanged) return;

      const success = await onSaveMemories(newMemories);
      if (success) {
        initialMemoriesRef.current = newMemories;
        setPopup({ message: "Memory saved", type: "success" });
      } else {
        setPopup({ message: "Failed to save memory", type: "error" });
      }
    },
    [localMemories, onSaveMemories, setPopup]
  );

  const filteredMemories = localMemories
    .map((memory, originalIndex) => ({ memory, originalIndex }))
    .filter(({ memory }) => {
      if (!searchQuery.trim()) return true;
      return memory.content
        .toLowerCase()
        .includes(searchQuery.trim().toLowerCase());
    });

  const totalLineCount = localMemories.filter(
    (m) => m.content.trim() || m.isNew
  ).length;

  return (
    <Modal open onOpenChange={(open) => !open && onClose()}>
      {popup}
      <Modal.Content width="sm" height="lg">
        <Modal.Header
          icon={SvgAddLines}
          title="Memory"
          description="Let Onyx reference these stored notes and memories in chats."
          onClose={onClose}
        >
          <Section flexDirection="row" gap={0.5}>
            <InputTypeIn
              placeholder="Search..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              leftSearchIcon
              className="w-full !bg-transparent !border-transparent [&:is(:hover,:active,:focus,:focus-within)]:!bg-background-neutral-00 [&:is(:hover)]:!border-border-01 [&:is(:focus,:focus-within)]:!shadow-none"
            />
            <Button
              onClick={handleAddMemory}
              tertiary
              rightIcon={SvgPlusCircle}
            >
              Add Line
            </Button>
          </Section>
        </Modal.Header>

        <Modal.Body padding={0.5}>
          {filteredMemories.length === 0 ? (
            <Section alignItems="center" padding={2}>
              <Text secondaryBody text03>
                {searchQuery.trim()
                  ? "No memories match your search."
                  : 'No memories yet. Click "Add Line" to get started.'}
              </Text>
            </Section>
          ) : (
            <Section gap={0.75}>
              {filteredMemories.map(({ memory, originalIndex }) => (
                <div
                  key={memory.id}
                  className="rounded-08 hover:bg-background-tint-00 w-full p-0.5"
                >
                  <Section gap={0.25} alignItems="start">
                    <Section flexDirection="row" alignItems="start" gap={0.5}>
                      <InputTextArea
                        placeholder="Type or paste in a personal note or memory"
                        value={memory.content}
                        onChange={(e) =>
                          handleUpdateMemory(originalIndex, e.target.value)
                        }
                        onBlur={() => void handleBlurMemory(originalIndex)}
                        rows={3}
                        maxLength={MAX_MEMORY_LENGTH}
                      />
                      <IconButton
                        icon={SvgMinusCircle}
                        onClick={() => void handleRemoveMemory(originalIndex)}
                        tertiary
                        disabled={!memory.content.trim() && memory.isNew}
                        aria-label="Remove Line"
                        tooltip="Remove Line"
                      />
                    </Section>
                    <Text secondaryBody text03>
                      ({memory.content.length}/{MAX_MEMORY_LENGTH} characters)
                    </Text>
                  </Section>
                </div>
              ))}
            </Section>
          )}
        </Modal.Body>

        <Modal.Footer justifyContent="center">
          <Text secondaryBody text03>
            {totalLineCount} {totalLineCount === 1 ? "Line" : "Lines"}
          </Text>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
