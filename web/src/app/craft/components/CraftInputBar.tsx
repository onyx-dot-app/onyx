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
import { useRouter } from "next/navigation";
import useSWR from "swr";
import BaseInputBar, {
  type BaseInputBarHandle,
} from "@/sections/input/BaseInputBar";
import EntryInfoPopover from "@/sections/input/EntryInfoPopover";
import EntryPickerPopover from "@/sections/input/EntryPickerPopover";
import InterruptHint from "@/app/craft/components/InterruptHint";
import { InputChipStrip } from "@/sections/input/InputChipStrip";
import { PlusMenuButton } from "@/sections/input/PlusMenuButton";
import { buildEntryMenuItems } from "@/app/craft/components/buildEntryMenuItems";
import UserLibraryModal from "@/app/craft/components/UserLibraryModal";
import { useEscapeInterrupt } from "@/hooks/useEscapeInterrupt";
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
import { SWR_KEYS } from "@/lib/swr-keys";
import { fetchLibraryTree } from "@/app/craft/services/apiServices";
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
      const fileInputRef = useRef<HTMLInputElement>(null);

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

      const { data: libraryTree, mutate: mutateLibrary } = useSWR(
        SWR_KEYS.buildUserLibraryTree,
        fetchLibraryTree
      );
      const libraryFiles = useMemo(
        () =>
          (libraryTree ?? [])
            .filter((entry) => !entry.is_directory)
            .map((entry) => ({ id: entry.id, name: entry.name })),
        [libraryTree]
      );
      const [libraryModalOpen, setLibraryModalOpen] = useState(false);

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

      useEscapeInterrupt({
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

      const router = useRouter();
      const plusMenuItems = useMemo(
        () =>
          buildEntryMenuItems(pickerSections, {
            onAttachFiles: () => fileInputRef.current?.click(),
            onSelectEntry: addEntry,
            onBrowseSkills: () => router.push("/craft/v1/skills"),
            onBrowseApps: () => router.push("/craft/v1/apps"),
            libraryFiles,
            // Defer the modal until the + popover finishes closing, else it paints over it.
            onManageLibrary: () =>
              window.setTimeout(() => setLibraryModalOpen(true), 200),
          }),
        [pickerSections, addEntry, libraryFiles, router]
      );

      const bottomLeftSlot = (
        <>
          <PlusMenuButton
            items={plusMenuItems}
            disabled={disabled}
            tooltip="Add files or skills"
          />
          {interruptible && <InterruptHint interrupting={isInterrupting} />}
        </>
      );

      return (
        <>
          <input
            ref={fileInputRef}
            type="file"
            className="hidden"
            multiple
            onChange={(e) => {
              const files = e.target.files;
              if (files && files.length > 0) uploadFiles(Array.from(files));
              e.target.value = "";
            }}
          />
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
            queuedMessages={queuedMessages}
            onQueueMessage={onQueueMessage}
            onRemoveQueuedMessage={onRemoveQueuedMessage}
            onInterrupt={onInterrupt}
            isInterrupting={isInterrupting}
            topSlot={topSlot}
            bottomLeftSlot={bottomLeftSlot}
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
          <UserLibraryModal
            open={libraryModalOpen}
            onClose={() => setLibraryModalOpen(false)}
            onChanges={() => mutateLibrary()}
          />
        </>
      );
    }
  )
);

CraftInputBar.displayName = "CraftInputBar";

export default CraftInputBar;
