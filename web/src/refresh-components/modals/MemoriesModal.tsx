"use client";

import { Fragment, useState, useRef, useEffect, useCallback } from "react";
import Modal from "@/refresh-components/Modal";
import { Section } from "@/layouts/general-layouts";
import { InputTypeIn } from "@opal/components";
import InputTextArea from "@/refresh-components/inputs/InputTextArea";
import Text from "@/refresh-components/texts/Text";
import { Button, Divider } from "@opal/components";
import CharacterCount from "@/refresh-components/CharacterCount";
import TextSeparator from "@/refresh-components/TextSeparator";
import { toast } from "@/hooks/useToast";
import { useModalClose } from "@/refresh-components/contexts/ModalContext";
import { SvgAddLines, SvgMinusCircle, SvgPlusCircle } from "@opal/icons";
import { useTranslation } from "react-i18next";
import {
  useMemoryManager,
  MAX_MEMORY_LENGTH,
  MAX_MEMORY_COUNT,
  LocalMemory,
} from "@/hooks/useMemoryManager";
import { cn } from "@opal/utils";
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
  const { t } = useTranslation();

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
            placeholder={t(
              "settings.memory.type_paste_placeholder",
              "Type or paste in a personal note or memory"
            )}
            value={memory.content}
            onChange={(e) => onUpdate(originalIndex, e.target.value)}
            onFocus={() => setIsFocused(true)}
            onBlur={() => {
              setIsFocused(false);
              void onBlur(originalIndex);
            }}
            onKeyDown={(e) => {
              if (
                e.key === "Enter" &&
                !e.shiftKey &&
                !e.nativeEvent.isComposing
              ) {
                e.preventDefault();
                textareaRef.current?.blur();
              }
            }}
            rows={1}
            autoResize
            maxRows={3}
            maxLength={MAX_MEMORY_LENGTH}
            resizable={false}
            className="bg-background-tint-01 hover:bg-background-tint-00 focus-within:bg-background-tint-00"
          />
          <Button
            disabled={!memory.content.trim() && memory.isNew}
            prominence="tertiary"
            icon={SvgMinusCircle}
            onClick={() => void onRemove(originalIndex)}
            aria-label={t("settings.memory.remove_line_aria", "Remove Line")}
            tooltip={t("settings.memory.remove_line_tooltip", "Remove Line")}
          />
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
  const { t } = useTranslation();

  // Self-fetching: when no props provided, fetch from UserProvider
  const { user, refreshUser, updateUserPersonalization } = useUser();
  const { handleSavePersonalization } = useUserPersonalization(
    user,
    updateUserPersonalization,
    {
      onSuccess: () =>
        toast.success(
          t("settings.chats.toast_prefs_saved", "Preferences saved")
        ),
      onError: () =>
        toast.error(
          t("settings.chats.toast_prefs_failed", "Failed to save preferences")
        ),
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
    onNotify: (message, type) => {
      let translated = message;
      if (message === "Memory saved") {
        translated = t("settings.memory.saved_success", "Memory saved");
      } else if (message === "Failed to save memory") {
        translated = t("settings.memory.saved_failed", "Failed to save memory");
      } else if (message === "Memory deleted") {
        translated = t("settings.memory.deleted_success", "Memory deleted");
      } else if (message === "Failed to delete memory") {
        translated = t(
          "settings.memory.deleted_failed",
          "Failed to delete memory"
        );
      }
      toast[type](translated);
    },
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
      <Modal.Content width="sm" height="lg" position="top">
        <Modal.Header
          icon={SvgAddLines}
          title={t("settings.memory.modal_title", "Memory")}
          description={t(
            "settings.memory.modal_desc",
            "Let Onyx reference these stored notes and memories in chats."
          )}
          onClose={close}
        >
          <Section flexDirection="row" gap={0.5}>
            <InputTypeIn
              placeholder={t("settings.memory.search_placeholder", "Search...")}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              searchIcon
            />
            <Button
              disabled={!canAddMemory}
              prominence="tertiary"
              onClick={onAddLine}
              rightIcon={SvgPlusCircle}
              title={
                !canAddMemory
                  ? t("settings.memory.max_reached", {
                      defaultValue: `Maximum of ${MAX_MEMORY_COUNT} memories reached`,
                      count: MAX_MEMORY_COUNT,
                    })
                  : undefined
              }
            >
              {t("settings.memory.add_line", "Add Line")}
            </Button>
          </Section>
        </Modal.Header>

        <Modal.Body padding={0.5}>
          {filteredMemories.length === 0 ? (
            <Section alignItems="center" padding={2}>
              <Text secondaryBody text03>
                {searchQuery.trim()
                  ? t(
                      "settings.memory.no_matches",
                      "No memories match your search."
                    )
                  : t(
                      "settings.memory.no_memories_yet",
                      'No memories yet. Click "Add Line" to get started.'
                    )}
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
                  {memory.isNew && (
                    <Divider paddingParallel="fit" paddingPerpendicular="fit" />
                  )}
                </Fragment>
              ))}
            </Section>
          )}
          <TextSeparator
            count={totalLineCount}
            text={
              totalLineCount === 1
                ? t("settings.memory.suffix_line", "Line")
                : t("settings.memory.suffix_lines", "Lines")
            }
          />
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}
