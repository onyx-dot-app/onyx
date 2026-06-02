"use client";

import {
  forwardRef,
  memo,
  useCallback,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import BaseInputBar, {
  type BaseInputBarHandle,
} from "@/sections/input/BaseInputBar";
import SkillInfoPopover from "@/sections/input/SkillInfoPopover";
import SkillPickerPopover from "@/sections/input/SkillPickerPopover";
import InterruptHint from "@/app/craft/components/InterruptHint";
import { SkillChipStrip } from "@/sections/input/SkillChipStrip";
import { PlusMenuButton } from "@/sections/input/PlusMenuButton";
import { useDoubleEscapeInterrupt } from "@/hooks/useDoubleEscapeInterrupt";
import {
  useUploadFilesContext,
  type BuildFile,
} from "@/app/craft/contexts/UploadFilesContext";
import useUserSkills from "@/hooks/useUserSkills";
import useUserExternalApps from "@/hooks/useUserExternalApps";
import { toPickerSections, type PickerEntry } from "@/lib/skills/picker";
import {
  reduceOnInput,
  reduceOnDismiss,
  reduceOnSelection,
  INITIAL_PICKER_SESSION,
  type PickerSession,
} from "@/lib/skills/pickerSession";
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

      const [activeSkills, setActiveSkills] = useState<PickerEntry[]>([]);
      const [session, setSession] = useState<PickerSession>(
        INITIAL_PICKER_SESSION
      );
      // Mirror `session` into a ref so the callbacks handed to the memoized
      // BaseInputBar keep a stable identity across picker-query changes.
      const sessionRef = useRef(session);
      sessionRef.current = session;
      const [anchorRect, setAnchorRect] = useState<DOMRect | null>(null);
      const [skillInfo, setSkillInfo] = useState<{
        entry: PickerEntry;
        chipEl: HTMLElement;
      } | null>(null);
      const dismissSkillInfo = useCallback(() => setSkillInfo(null), []);

      const interruptible = !!onInterrupt && isRunning;
      const handleInterrupt = useCallback(() => {
        if (interruptible && !isInterrupting) onInterrupt?.();
      }, [interruptible, isInterrupting, onInterrupt]);

      const { armed } = useDoubleEscapeInterrupt({
        enabled:
          interruptible && !isInterrupting && !session.open && !skillInfo,
        onInterrupt: handleInterrupt,
      });

      const addSkill = useCallback((entry: PickerEntry) => {
        setActiveSkills((prev) =>
          prev.some((e) => e.slug === entry.slug) ? prev : [...prev, entry]
        );
      }, []);

      const removeSkill = useCallback((slug: string) => {
        setActiveSkills((prev) => prev.filter((e) => e.slug !== slug));
      }, []);

      useImperativeHandle(ref, () => ({
        reset: () => {
          baseRef.current?.reset();
          setActiveSkills([]);
          clearFiles();
          setSession(INITIAL_PICKER_SESSION);
        },
        focus: () => baseRef.current?.focus(),
        setMessage: (msg: string) => baseRef.current?.setMessage(msg),
      }));

      // ── Slash picker ──────────────────────────────────────────────────────

      const closeSkillPicker = useCallback(
        () => setSession(INITIAL_PICKER_SESSION),
        []
      );
      const dismissSkillPicker = useCallback(
        () => setSession(reduceOnDismiss),
        []
      );

      const handleInputCallback = useCallback(() => {
        const text = baseRef.current?.getTextBeforeCursor() ?? null;
        const next = reduceOnInput(sessionRef.current, text);
        if (next.open) setAnchorRect(baseRef.current?.getCaretRect() ?? null);
        setSession(next);
      }, []);

      const handleSkillPickerSelect = useCallback(
        (entry: PickerEntry) => {
          if (!session.open) return;
          baseRef.current?.deleteBeforeToken(`/${session.query}`);
          addSkill(entry);
          closeSkillPicker();
        },
        [session, addSkill, closeSkillPicker]
      );

      // ── Extension hooks ───────────────────────────────────────────────────

      const onBeforeKeyDown = useCallback(
        (_event: KeyboardEvent<HTMLDivElement>): boolean => {
          const current = sessionRef.current;
          if (current.open) {
            const text = baseRef.current?.getTextBeforeCursor() ?? null;
            const next = reduceOnSelection(current, text);
            if (next.open)
              setAnchorRect(baseRef.current?.getCaretRect() ?? null);
            setSession(next);
          }
          return false;
        },
        []
      );

      const onPasteText = useCallback(
        (text: string): boolean => {
          const slug = text.trim().match(/^\/(\S+)$/)?.[1];
          const entry = slug
            ? ([...pickerSections.skills, ...pickerSections.apps].find(
                (e) => e.slug === slug
              ) ?? null)
            : null;
          if (entry) {
            addSkill(entry);
            return true;
          }
          return false;
        },
        [pickerSections, addSkill]
      );

      // ── Submit ────────────────────────────────────────────────────────────

      const handleSubmit = useCallback(
        (message: string) => {
          const skillPrefixes = activeSkills.map((e) => `/${e.slug}`).join(" ");
          const fullMessage = skillPrefixes
            ? `${skillPrefixes} ${message}`
            : message;
          onSubmit(fullMessage, currentMessageFiles);
          setActiveSkills([]);
          clearFiles({ suppressRefetch: true });
        },
        [activeSkills, currentMessageFiles, onSubmit, clearFiles]
      );

      // ── Slots ─────────────────────────────────────────────────────────────

      const topSlot =
        currentMessageFiles.length > 0 || activeSkills.length > 0 ? (
          <SkillChipStrip
            files={currentMessageFiles}
            skills={activeSkills}
            onRemoveFile={removeFile}
            onRemoveSkill={removeSkill}
            onClickSkill={(entry, chipEl) => setSkillInfo({ entry, chipEl })}
          />
        ) : undefined;

      const bottomLeftSlot = (
        <>
          <PlusMenuButton
            sections={pickerSections}
            onSelectEntry={addSkill}
            onAttachFiles={() => fileInputRef.current?.click()}
            disabled={disabled}
          />
          {interruptible && (
            <InterruptHint armed={armed} interrupting={isInterrupting} />
          )}
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
            stopArmed={armed}
            queuedMessages={queuedMessages}
            onQueueMessage={onQueueMessage}
            onRemoveQueuedMessage={onRemoveQueuedMessage}
            onInterrupt={onInterrupt}
            isInterrupting={isInterrupting}
            topSlot={topSlot}
            bottomLeftSlot={bottomLeftSlot}
            onBeforeKeyDown={onBeforeKeyDown}
            onPasteText={onPasteText}
            onPasteFiles={uploadFiles}
            onInputCallback={handleInputCallback}
          />
          <SkillPickerPopover
            open={session.open}
            anchorRect={anchorRect}
            query={session.query}
            sections={pickerSections}
            onSelect={handleSkillPickerSelect}
            onClose={dismissSkillPicker}
          />
          {skillInfo && (
            <SkillInfoPopover
              name={skillInfo.entry.name}
              description={
                skillInfo.entry.kind === "skill"
                  ? skillInfo.entry.description
                  : skillInfo.entry.description
              }
              tileElement={skillInfo.chipEl}
              onDismiss={dismissSkillInfo}
            />
          )}
        </>
      );
    }
  )
);

CraftInputBar.displayName = "CraftInputBar";

export default CraftInputBar;
