"use client";

import { useState } from "react";
import Modal from "@/refresh-components/Modal";
import { Section } from "@/layouts/general-layouts";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import InputTextArea from "@/refresh-components/inputs/InputTextArea";
import IconButton from "@/refresh-components/buttons/IconButton";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import CharacterCount from "@/refresh-components/CharacterCount";
import TextSeparator from "@/refresh-components/TextSeparator";
import { usePopup } from "@/components/admin/connectors/Popup";
import { useModalClose } from "@/refresh-components/contexts/ModalContext";
import { SvgAddLines, SvgMinusCircle, SvgPlusCircle } from "@opal/icons";
import {
  useMemoryManager,
  MAX_MEMORY_LENGTH,
  LocalMemory,
} from "@/hooks/useMemoryManager";
import { cn } from "@/lib/utils";

interface MemoryItemProps {
  memory: LocalMemory;
  originalIndex: number;
  onUpdate: (index: number, value: string) => void;
  onBlur: (index: number) => void;
  onRemove: (index: number) => void;
}

function MemoryItem({
  memory,
  originalIndex,
  onUpdate,
  onBlur,
  onRemove,
}: MemoryItemProps) {
  const [isFocused, setIsFocused] = useState(false);

  return (
    <div className="rounded-08 hover:bg-background-tint-00 w-full p-0.5">
      <Section gap={0.25} alignItems="start">
        <Section flexDirection="row" alignItems="start" gap={0.5}>
          <InputTextArea
            placeholder="Type or paste in a personal note or memory"
            value={memory.content}
            onChange={(e) => onUpdate(originalIndex, e.target.value)}
            onFocus={() => setIsFocused(true)}
            onBlur={() => {
              setIsFocused(false);
              void onBlur(originalIndex);
            }}
            rows={3}
            maxLength={MAX_MEMORY_LENGTH}
            className={cn("resize-none", !isFocused && "bg-transparent")}
          />
          <IconButton
            icon={SvgMinusCircle}
            onClick={() => void onRemove(originalIndex)}
            tertiary
            disabled={!memory.content.trim() && memory.isNew}
            aria-label="Remove Line"
            tooltip="Remove Line"
          />
        </Section>
        {isFocused && (
          <CharacterCount value={memory.content} limit={MAX_MEMORY_LENGTH} />
        )}
      </Section>
    </div>
  );
}

interface MemoriesModalProps {
  memories: string[];
  onSaveMemories: (memories: string[]) => Promise<boolean>;
  onClose?: () => void;
}

export default function MemoriesModal({
  memories,
  onSaveMemories,
  onClose,
}: MemoriesModalProps) {
  const close = useModalClose(onClose);
  const { popup, setPopup } = usePopup();

  const {
    searchQuery,
    setSearchQuery,
    filteredMemories,
    totalLineCount,
    handleAddMemory,
    handleUpdateMemory,
    handleRemoveMemory,
    handleBlurMemory,
  } = useMemoryManager({
    memories,
    onSaveMemories,
    onNotify: (message, type) => setPopup({ message, type }),
  });

  return (
    <Modal open onOpenChange={(open) => !open && close?.()}>
      {popup}
      <Modal.Content width="sm" height="lg">
        <Modal.Header
          icon={SvgAddLines}
          title="Memory"
          description="Let Onyx reference these stored notes and memories in chats."
          onClose={close}
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
            <Section gap={0.5}>
              {filteredMemories.map(({ memory, originalIndex }) => (
                <MemoryItem
                  key={memory.id}
                  memory={memory}
                  originalIndex={originalIndex}
                  onUpdate={handleUpdateMemory}
                  onBlur={handleBlurMemory}
                  onRemove={handleRemoveMemory}
                />
              ))}
            </Section>
          )}
          <TextSeparator
            count={totalLineCount}
            text={totalLineCount === 1 ? "Line" : "Lines"}
          />
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}
