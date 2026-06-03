"use client";

import {
  forwardRef,
  memo,
  useCallback,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import BaseInputBar, {
  type BaseInputBarHandle,
} from "@/sections/input/BaseInputBar";
import EntryInfoPopover from "@/sections/input/EntryInfoPopover";
import EntryPickerPopover from "@/sections/input/EntryPickerPopover";
import InterruptHint from "@/app/craft/components/InterruptHint";
import { InputChipStrip } from "@/sections/input/InputChipStrip";
import { PlusMenuButton } from "@/sections/input/PlusMenuButton";
import HiddenFileInput, {
  type HiddenFileInputHandle,
} from "@/refresh-components/inputs/HiddenFileInput";
import { buildEntryMenuItems } from "@/app/craft/components/buildEntryMenuItems";
import { useDoubleEscapeInterrupt } from "@/hooks/useDoubleEscapeInterrupt";
import useSlashPicker from "@/hooks/useSlashPicker";
import {
  useUploadFilesContext,
  type BuildFile,
} from "@/app/craft/contexts/UploadFilesContext";
import useUserSkills from "@/hooks/useUserSkills";
import useUserExternalApps from "@/hooks/useUserExternalApps";
import {
  toPickerSections,
  flattenSections,
  type PickerEntry,
} from "@/lib/skills/picker";
import type { QueuedMessage } from "@/app/app/interfaces";

export interface CraftInputBarHandle {
  reset: () => void;
  focus: () => void;
  setMessage: (message: string) => void;
}

export interface CraftInputBarProps {
  onSubmit: (message: string, files: BuildFile[]) => void;
  isRunning: boolean;
  disabled?: boolean;
  placeholder?: string;
  sandboxInitializing?: boolean;
  noBottomRounding?: boolean;
  queuedMessages?: readonly QueuedMessage[];
  onQueueMessage?: (text: string) => void;
  onRemoveQueuedMessage?: (index: number) => void;
  onInterrupt?: () => void;
  isInterrupting?: boolean;
  /** Seed the active entry chips. For stories/tests; production callers leave unset. */
  initialEntries?: PickerEntry[];
}

const CraftInputBar = memo(
  forwardRef<CraftInputBarHandle, CraftInputBarProps>(
    (
      {
        onSubmit,
        isRunning,
        disabled = false,
        placeholder,
        sandboxInitializing = false,
        noBottomRounding = false,
        queuedMessages,
        onQueueMessage,
        onRemoveQueuedMessage,
        onInterrupt,
        isInterrupting = false,
        initialEntries,
      },
      ref
    ) => {
      const baseRef = useRef<BaseInputBarHandle>(null);
      const fileInputRef = useRef<HiddenFileInputHandle>(null);

      const {
        currentMessageFiles,
        uploadFiles,
        removeFile,
        clearFiles,
        hasUploadingFiles,
      } = useUploadFilesContext();

      const { data: skillsData } = useUserSkills();
      const { data: appsData } = useUserExternalApps();
      const pickerSections = useMemo(
        () => toPickerSections(skillsData, appsData),
        [skillsData, appsData]
      );

      const [activeEntries, setActiveEntries] = useState<PickerEntry[]>(
        initialEntries ?? []
      );
      const [entryInfo, setEntryInfo] = useState<{
        entry: PickerEntry;
        chipEl: HTMLElement;
      } | null>(null);
      const dismissEntryInfo = useCallback(() => setEntryInfo(null), []);

      const addEntry = useCallback((entry: PickerEntry) => {
        setActiveEntries((prev) =>
          prev.some((e) => e.slug === entry.slug) ? prev : [...prev, entry]
        );
      }, []);

      const removeEntry = useCallback((slug: string) => {
        setActiveEntries((prev) => prev.filter((e) => e.slug !== slug));
      }, []);

      const slashPicker = useSlashPicker({
        inputRef: baseRef,
        onSelect: addEntry,
      });

      const interruptible = !!onInterrupt && isRunning;
      const handleInterrupt = useCallback(() => {
        if (interruptible && !isInterrupting) onInterrupt?.();
      }, [interruptible, isInterrupting, onInterrupt]);

      const { armed } = useDoubleEscapeInterrupt({
        enabled:
          interruptible && !isInterrupting && !slashPicker.open && !entryInfo,
        onInterrupt: handleInterrupt,
      });

      useImperativeHandle(ref, () => ({
        reset: () => {
          baseRef.current?.reset();
          setActiveEntries([]);
          clearFiles();
          slashPicker.reset();
        },
        focus: () => baseRef.current?.focus(),
        setMessage: (msg: string) => baseRef.current?.setMessage(msg),
      }));

      const onPasteText = useCallback(
        (text: string): boolean => {
          const slug = text.trim().match(/^\/(\S+)$/)?.[1];
          const entry = slug
            ? (flattenSections(pickerSections).find((e) => e.slug === slug) ??
              null)
            : null;
          if (entry) {
            addEntry(entry);
            return true;
          }
          return false;
        },
        [pickerSections, addEntry]
      );

      const handleSubmit = useCallback(
        (message: string) => {
          const skillPrefixes = activeEntries
            .map((e) => `/${e.slug}`)
            .join(" ");
          const fullMessage = skillPrefixes
            ? `${skillPrefixes} ${message}`
            : message;
          onSubmit(fullMessage, currentMessageFiles);
          setActiveEntries([]);
          clearFiles({ suppressRefetch: true });
        },
        [activeEntries, currentMessageFiles, onSubmit, clearFiles]
      );

      // Always rendered so the strip can animate its own collapse/expand.
      const topSlot = (
        <InputChipStrip
          files={currentMessageFiles}
          entries={activeEntries}
          onRemoveFile={removeFile}
          onRemoveEntry={removeEntry}
          onClickEntry={(entry, chipEl) => setEntryInfo({ entry, chipEl })}
        />
      );

      const plusMenuItems = useMemo(
        () =>
          buildEntryMenuItems(pickerSections, {
            onAttachFiles: () => fileInputRef.current?.open(),
            onSelectEntry: addEntry,
          }),
        [pickerSections, addEntry]
      );

      const bottomLeftSlot = (
        <>
          <PlusMenuButton
            items={plusMenuItems}
            disabled={disabled}
            tooltip="Add files or skills"
          />
          {interruptible && (
            <InterruptHint armed={armed} interrupting={isInterrupting} />
          )}
        </>
      );

      return (
        <>
          <HiddenFileInput ref={fileInputRef} multiple onFiles={uploadFiles} />
          <BaseInputBar
            ref={baseRef}
            onSubmit={handleSubmit}
            isRunning={isRunning}
            disabled={disabled}
            placeholder={placeholder}
            noBottomRounding={noBottomRounding}
            pasteTilesEnabled
            sandboxInitializing={sandboxInitializing}
            submitBlocked={hasUploadingFiles}
            stopArmed={armed}
            queuedMessages={queuedMessages}
            onQueueMessage={onQueueMessage}
            onRemoveQueuedMessage={onRemoveQueuedMessage}
            onInterrupt={onInterrupt}
            isInterrupting={isInterrupting}
            topSlot={topSlot}
            bottomLeftSlot={bottomLeftSlot}
            onBeforeKeyDown={slashPicker.onBeforeKeyDown}
            onPasteText={onPasteText}
            onPasteFiles={uploadFiles}
            onInputCallback={slashPicker.onInput}
            onSelectionChange={slashPicker.onSelectionChange}
          />
          <EntryPickerPopover
            open={slashPicker.open}
            anchorRect={slashPicker.anchorRect}
            query={slashPicker.query}
            sections={pickerSections}
            onSelect={slashPicker.onSelect}
            onClose={slashPicker.onClose}
          />
          {entryInfo && (
            <EntryInfoPopover
              name={entryInfo.entry.name}
              description={entryInfo.entry.description}
              tileElement={entryInfo.chipEl}
              onDismiss={dismissEntryInfo}
            />
          )}
        </>
      );
    }
  )
);

CraftInputBar.displayName = "CraftInputBar";

export default CraftInputBar;
