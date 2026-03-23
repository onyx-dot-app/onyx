"use client";

import { Fragment, useState, useRef, useEffect, useCallback } from "react";
import Modal from "@/refresh-components/Modal";
import { Section } from "@/layouts/general-layouts";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import InputTextArea from "@/refresh-components/inputs/InputTextArea";
import Text from "@/refresh-components/texts/Text";
import { Button } from "@opal/components";
import { Disabled } from "@opal/core";
import CharacterCount from "@/refresh-components/CharacterCount";
import Separator from "@/refresh-components/Separator";
import TextSeparator from "@/refresh-components/TextSeparator";
import { toast } from "@/hooks/useToast";
import { useModalClose } from "@/refresh-components/contexts/ModalContext";
import { SvgAddLines, SvgMinusCircle, SvgPlusCircle } from "@opal/icons";
import {
  useMemoryManager,
  MAX_MEMORY_LENGTH,
  MAX_MEMORY_COUNT,
  LocalMemory,
} from "@/hooks/useMemoryManager";
import { cn } from "@/lib/utils";
import { useUser } from "@/providers/UserProvider";
import useUserPersonalization from "@/hooks/useUserPersonalization";
import type { MemoryItem } from "@/lib/types";

interface MemoryItemProps {
  memory: LocalMemory;
  originalIndex: number;
  onUpdate: (index: number, value: string) => void;
  onBlur: (index: number) => void;
  onRemove: (index: number) => void;
  shouldFocus?: boolean;
  onFocused?: () => void;
  shouldHighlight?: boolean;
  onHighlighted?: () => void;
}

function MemoryItem({
  memory,
  originalIndex,
  onUpdate,
  onBlur,
  onRemove,
  shouldFocus,
  onFocused,
  shouldHighlight,
  onHighlighted,
}: MemoryItemProps) {
  const [isFocused, setIsFocused] = useState(false);
  const [isHighlighting, setIsHighlighting] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (shouldFocus && textareaRef.current) {
      const el = textareaRef.current;
      el.focus();
      el.selectionStart = el.selectionEnd = el.value.length;
      onFocused?.();
    }
  }, [shouldFocus, onFocused]);

  useEffect(() => {
    if (!shouldHighlight) return;

    wrapperRef.current?.scrollIntoView({
      block: "start",
      behavior: "smooth",
    });
    setIsHighlighting(true);

    const timer = setTimeout(() => {
      setIsHighlighting(false);
      onHighlighted?.();
    }, 1000);

    return () => clearTimeout(timer);
  }, [shouldHighlight, onHighlighted]);

  return (
    <div
      ref={wrapperRef}
      className={cn(
        "rounded-08 w-full p-0.5 border border-transparent",
        "transition-colors ",
        isHighlighting &&
          "bg-action-link-01 hover:bg-action-link-01 border-action-link-05 duration-700"
      )}
    >
      <Section gap={0.25} alignItems="start">
        <Section flexDirection="row" alignItems="start" gap={0.5}>
          <InputTextArea
            ref={textareaRef}
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
            resizable={false}
            className="bg-background-tint-01 hover:bg-background-tint-00 focus-within:bg-background-tint-00"
          />
          <Disabled disabled={!memory.content.trim() && memory.isNew}>
            <Button
              prominence="tertiary"
              icon={SvgMinusCircle}
              onClick={() => void onRemove(originalIndex)}
              aria-label="Remove Line"
              tooltip="Remove Line"
            />
          </Disabled>
        </Section>
        <div
          className={isFocused ? "visible" : "invisible h-0 overflow-hidden"}
        >
          <CharacterCount value={memory.content} limit={MAX_MEMORY_LENGTH} />
        </div>
      </Section>
    </div>
  );
}

function resolveTargetMemoryId(
  targetMemoryId: number | null | undefined,
  targetIndex: number | null | undefined,
  memories: MemoryItem[]
): number | null {
  if (targetMemoryId != null) return targetMemoryId;

  if (targetIndex != null && memories.length > 0) {
    // Backend index is ASC (oldest-first), frontend displays DESC (newest-first)
    const descIdx = memories.length - 1 - targetIndex;
    return memories[descIdx]?.id ?? null;
  }

  return null;
}

interface MemoriesModalProps {
  memories?: MemoryItem[];
  onSaveMemories?: (memories: MemoryItem[]) => Promise<boolean>;
  onClose?: () => void;
  initialTargetMemoryId?: number | null;
  initialTargetIndex?: number | null;
  highlightOnOpen?: boolean;
  focusNewLine?: boolean;
}

export default function MemoriesModal({
  memories: memoriesProp,
  onSaveMemories: onSaveMemoriesProp,
  onClose,
  initialTargetMemoryId,
  initialTargetIndex,
  highlightOnOpen = false,
  focusNewLine = false,
}: MemoriesModalProps) {
  const close = useModalClose(onClose);
  const [focusMemoryId, setFocusMemoryId] = useState<number | null>(null);

  // Self-fetching: when no props provided, fetch from UserProvider
  const { user, refreshUser, updateUserPersonalization } = useUser();
  const { handleSavePersonalization } = useUserPersonalization(
    user,
    updateUserPersonalization,
    {
      onSuccess: () => toast.success("Preferences saved"),
      onError: () => toast.error("Failed to save preferences"),
    }
  );

  useEffect(() => {
    if (memoriesProp === undefined) {
      void refreshUser();
    }
    // Only run on mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const internalSaveMemories = useCallback(
    async (newMemories: MemoryItem[]): Promise<boolean> => {
      const result = await handleSavePersonalization(
        { memories: newMemories },
        true
      );
      return !!result;
    },
    [handleSavePersonalization]
  );

  const effectiveMemories =
    memoriesProp ?? user?.personalization?.memories ?? [];
  const effectiveSave = onSaveMemoriesProp ?? internalSaveMemories;

  // Drives scroll-into-view + highlight when opening from a FileTile click
  const [highlightMemoryId, setHighlightMemoryId] = useState<number | null>(
    null
  );

  useEffect(() => {
    const targetId = resolveTargetMemoryId(
      initialTargetMemoryId,
      initialTargetIndex,
      effectiveMemories
    );
    if (targetId == null) return;

    setFocusMemoryId(targetId);
    if (highlightOnOpen) {
      setHighlightMemoryId(targetId);
    }
  }, [initialTargetMemoryId, initialTargetIndex]);

  const {
    searchQuery,
    setSearchQuery,
    filteredMemories,
    totalLineCount,
    canAddMemory,
    handleAddMemory,
    handleUpdateMemory,
    handleRemoveMemory,
    handleBlurMemory,
  } = useMemoryManager({
    memories: effectiveMemories,
    onSaveMemories: effectiveSave,
    onNotify: (message, type) => toast[type](message),
  });

  // Always start with an empty card; optionally focus it (View/Add button)
  const hasAddedEmptyRef = useRef(false);
  useEffect(() => {
    if (hasAddedEmptyRef.current) return;
    hasAddedEmptyRef.current = true;

    const id = handleAddMemory();
    if (id !== null && focusNewLine) {
      setFocusMemoryId(id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onAddLine = () => {
    const id = handleAddMemory();
    if (id !== null) {
      setFocusMemoryId(id);
    }
  };

  return (
    <Modal open onOpenChange={(open) => !open && close?.()}>
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
              showClearButton={false}
              className="w-full !bg-transparent !border-transparent [&:is(:hover,:active,:focus,:focus-within)]:!bg-background-neutral-00 [&:is(:hover)]:!border-border-01 [&:is(:focus,:focus-within)]:!shadow-none"
            />
            <Disabled disabled={!canAddMemory}>
              <Button
                prominence="tertiary"
                onClick={onAddLine}
                rightIcon={SvgPlusCircle}
                title={
                  !canAddMemory
                    ? `Maximum of ${MAX_MEMORY_COUNT} memories reached`
                    : undefined
                }
              >
                Add Line
              </Button>
            </Disabled>
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
                <Fragment key={memory.id}>
                  <MemoryItem
                    memory={memory}
                    originalIndex={originalIndex}
                    onUpdate={handleUpdateMemory}
                    onBlur={handleBlurMemory}
                    onRemove={handleRemoveMemory}
                    shouldFocus={memory.id === focusMemoryId}
                    onFocused={() => setFocusMemoryId(null)}
                    shouldHighlight={memory.id === highlightMemoryId}
                    onHighlighted={() => {
                      setHighlightMemoryId(null);
                    }}
                  />
                  {memory.isNew && <Separator noPadding />}
                </Fragment>
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
