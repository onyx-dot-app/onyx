"use client";

import {
  memo,
  forwardRef,
  useImperativeHandle,
  useCallback,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type ClipboardEvent,
  type KeyboardEvent,
  type MouseEvent,
  type SyntheticEvent,
} from "react";
import { getPastedFilesIfNoText } from "@/lib/clipboard";
import { isImageFile } from "@/lib/utils";
import PasteTilePopover from "@/sections/input/PasteTilePopover";
import SkillPickerPopover from "@/sections/input/SkillPickerPopover";
import SkillInfoPopover from "@/sections/input/SkillInfoPopover";
import { cn } from "@opal/utils";
import { Disabled } from "@opal/core";
import {
  useUploadFilesContext,
  BuildFile,
  UploadFileStatus,
} from "@/app/craft/contexts/UploadFilesContext";
import IconButton from "@/refresh-components/buttons/IconButton";
import { Button, Text, Tooltip } from "@opal/components";
import {
  SvgArrowUp,
  SvgClock,
  SvgFileText,
  SvgImage,
  SvgLoader,
  SvgStop,
  SvgX,
  SvgPaperclip,
  SvgAlertCircle,
} from "@opal/icons";
import InterruptHint from "@/app/craft/components/InterruptHint";
import Keycap from "@/refresh-components/Keycap";
import { useDoubleEscapeInterrupt } from "@/hooks/useDoubleEscapeInterrupt";
import { useContentEditable } from "@/hooks/useContentEditable";
import useUserSkills from "@/hooks/useUserSkills";
import { toPickerSkills } from "@/lib/skills/picker";
import {
  reduceOnInput,
  reduceOnSelection,
  reduceOnDismiss,
  INITIAL_PICKER_SESSION,
  type PickerSession,
} from "@/lib/skills/pickerSession";
import { getTextContent } from "@/lib/contentEditable";
import { isSkillTile } from "@/lib/richInputTile";
import QueuedMessageBar from "@/sections/input/QueuedMessageBar";
import { useQueuedMessageNavigation } from "@/hooks/useQueuedMessageNavigation";
import {
  QueuedMessage,
  MAX_QUEUED_MESSAGES,
  EMPTY_QUEUED_MESSAGES,
} from "@/app/app/interfaces";

export interface InputBarHandle {
  reset: () => void;
  focus: () => void;
  setMessage: (message: string) => void;
}

export interface InputBarProps {
  onSubmit: (message: string, files: BuildFile[]) => void;
  isRunning: boolean;
  disabled?: boolean;
  placeholder?: string;
  sandboxInitializing?: boolean;
  noBottomRounding?: boolean;
  /** Queued messages + callbacks; when wired, submitting mid-stream enqueues. */
  queuedMessages?: readonly QueuedMessage[];
  onQueueMessage?: (text: string) => void;
  onRemoveQueuedMessage?: (index: number) => void;
  /** Interrupt the in-flight turn; when wired, shows the Stop control + Esc hint. */
  onInterrupt?: () => void;
  /** Interrupt requested, awaiting the turn to terminate. */
  isInterrupting?: boolean;
}

/**
 * Simple file card for displaying attached files
 */
function BuildFileCard({
  file,
  onRemove,
}: {
  file: BuildFile;
  onRemove: (id: string) => void;
}) {
  const isImage = isImageFile(file.name);
  const isUploading = file.status === UploadFileStatus.UPLOADING;
  const isPending = file.status === UploadFileStatus.PENDING;
  const isFailed = file.status === UploadFileStatus.FAILED;

  const cardContent = (
    <div
      className={cn(
        "flex items-center gap-1.5 px-2 py-1 rounded-08",
        "bg-background-neutral-01 border",
        "text-sm text-text-04",
        isFailed ? "border-status-error-02" : "border-border-01"
      )}
    >
      {isUploading ? (
        <SvgLoader className="h-4 w-4 animate-spin text-text-03" />
      ) : isPending ? (
        <SvgClock className="h-4 w-4 text-text-03" />
      ) : isFailed ? (
        <SvgAlertCircle className="h-4 w-4 text-status-error-02" />
      ) : isImage ? (
        <SvgImage className="h-4 w-4 text-text-03" />
      ) : (
        <SvgFileText className="h-4 w-4 text-text-03" />
      )}
      <span className="max-w-[120px] truncate">
        <Text font="main-ui-body" color="text-04" nowrap>
          {file.name}
        </Text>
      </span>
      <Button
        variant="default"
        prominence="tertiary"
        size="2xs"
        icon={SvgX}
        onClick={() => onRemove(file.id)}
        aria-label={`Remove ${file.name}`}
      />
    </div>
  );

  // Wrap in tooltip for error or pending status
  if (isFailed && file.error) {
    return (
      <Tooltip tooltip={file.error} side="top">
        {cardContent}
      </Tooltip>
    );
  }

  if (isPending) {
    return (
      <Tooltip tooltip="Waiting for session to be ready..." side="top">
        {cardContent}
      </Tooltip>
    );
  }

  return cardContent;
}

/**
 * InputBar - Text input with file attachment support
 *
 * File upload state is managed by UploadFilesContext. This component just:
 * - Triggers file selection/paste
 * - Displays attached files
 * - Handles message submission
 *
 * The context handles:
 * - Session binding (which session to upload to)
 * - Auto-upload when session becomes available
 * - Fetching existing attachments on session change
 */
const InputBar = memo(
  forwardRef<InputBarHandle, InputBarProps>(
    (
      {
        onSubmit,
        isRunning,
        disabled = false,
        placeholder = "Describe your task...",
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
      // Queueing is enabled only when the parent wires up the callbacks.
      const queueEnabled = !!onQueueMessage;
      const queue = queuedMessages ?? EMPTY_QUEUED_MESSAGES;
      const inputWrapperRef = useRef<HTMLDivElement>(null);
      const {
        ref: inputRef,
        message,
        setMessage,
        clearMessage,
        handleInput: onInput,
        handleCompositionStart,
        handleCompositionEnd,
        pasteText,
        insertSkillTile,
        handleCopy,
        handleCut,
        setCursorToEnd,
        handleTileMouseDown,
        handleTileClick,
        handleTileKeyDown,
        tilePopover,
        dismissTilePopover,
        updateTileText,
      } = useContentEditable({
        wrapperRef: inputWrapperRef,
        // Craft always collapses large pastes into tiles, regardless of the
        // user's paste_as_tile preference.
        pasteTilesEnabled: true,
      });

      const containerRef = useRef<HTMLDivElement>(null);
      const fileInputRef = useRef<HTMLInputElement>(null);

      const {
        currentMessageFiles,
        uploadFiles,
        removeFile,
        clearFiles,
        hasUploadingFiles,
      } = useUploadFilesContext();

      const { data: skillsData } = useUserSkills();
      const pickerSkills = useMemo(
        () => toPickerSkills(skillsData),
        [skillsData]
      );
      const [session, setSession] = useState<PickerSession>(
        INITIAL_PICKER_SESSION
      );
      const [anchorRect, setAnchorRect] = useState<DOMRect | null>(null);

      const [skillInfo, setSkillInfo] = useState<{
        tile: HTMLElement;
        name: string;
        description: string;
      } | null>(null);
      const dismissSkillInfo = useCallback(() => setSkillInfo(null), []);

      const queueNav = useQueuedMessageNavigation({
        messages: queue,
        inputIsEmpty: !message,
        onRemove: (index) => onRemoveQueuedMessage?.(index),
        onEdit: setMessage,
      });

      const getTextBeforeCursor = useCallback((): string | null => {
        const el = inputRef.current;
        if (!el) return null;
        const sel = window.getSelection();
        if (!sel || sel.rangeCount === 0) return null;
        const range = sel.getRangeAt(0);
        if (!el.contains(range.startContainer)) return null;
        const cloned = range.cloneRange();
        cloned.selectNodeContents(el);
        cloned.setEnd(range.startContainer, range.startOffset);
        const tmp = document.createElement("div");
        tmp.appendChild(cloned.cloneContents());
        return getTextContent(tmp);
      }, [inputRef]);

      const getCaretRect = useCallback((): DOMRect | null => {
        const sel = window.getSelection();
        if (!sel || sel.rangeCount === 0) return null;
        const range = sel.getRangeAt(0).cloneRange();
        range.collapse(true);
        const rect = range.getBoundingClientRect();
        if (
          rect.top === 0 &&
          rect.left === 0 &&
          rect.width === 0 &&
          rect.height === 0
        ) {
          return inputRef.current?.getBoundingClientRect() ?? null;
        }
        return rect;
      }, [inputRef]);

      const closeSkillPicker = useCallback(
        () => setSession(INITIAL_PICKER_SESSION),
        []
      );

      const dismissSkillPicker = useCallback(
        () => setSession(reduceOnDismiss),
        []
      );

      const handleEnhancedInput = useCallback(
        (event: SyntheticEvent<HTMLDivElement>) => {
          onInput(event);
          const next = reduceOnInput(session, getTextBeforeCursor());
          if (next.open) setAnchorRect(getCaretRect());
          setSession(next);
        },
        [onInput, session, getTextBeforeCursor, getCaretRect]
      );

      const handleSelectionChange = useCallback(() => {
        if (!session.open) return;
        const next = reduceOnSelection(session, getTextBeforeCursor());
        if (next.open) setAnchorRect(getCaretRect());
        setSession(next);
      }, [session, getTextBeforeCursor, getCaretRect]);

      const handleSkillPickerSelect = useCallback(
        (slug: string) => {
          if (!session.open) return;
          const beforeToken = `/${session.query}`;
          const name = pickerSkills.find((s) => s.slug === slug)?.name ?? slug;
          if (insertSkillTile(slug, name, beforeToken)) closeSkillPicker();
        },
        [
          session.open,
          session.query,
          pickerSkills,
          insertSkillTile,
          closeSkillPicker,
        ]
      );

      const openSkillInfo = useCallback(
        (tile: HTMLElement) => {
          const slug = tile.getAttribute("data-skill-slug") ?? "";
          const skill = pickerSkills.find((s) => s.slug === slug);
          setSkillInfo({
            tile,
            name: skill?.name ?? slug,
            description: skill?.description ?? "",
          });
        },
        [pickerSkills]
      );

      // Clicking a skill tile opens an info popover with its name + description.
      // Other clicks fall through to the paste-tile handler.
      const handleInputClick = useCallback(
        (event: MouseEvent<HTMLDivElement>) => {
          const target = event.target as HTMLElement;
          const tile = target.closest("[data-rich-tile]") as HTMLElement | null;
          if (
            tile &&
            isSkillTile(tile) &&
            !target.closest("[data-rich-tile-remove]")
          ) {
            openSkillInfo(tile);
            return;
          }
          handleTileClick(event);
        },
        [openSkillInfo, handleTileClick]
      );

      useImperativeHandle(ref, () => ({
        reset: () => {
          clearMessage();
          clearFiles();
          closeSkillPicker();
        },
        focus: () => {
          inputRef.current?.focus();
          setCursorToEnd();
        },
        setMessage: (msg: string) => {
          setMessage(msg);
        },
      }));

      const handleFileSelect = useCallback(
        async (e: ChangeEvent<HTMLInputElement>) => {
          const files = e.target.files;
          if (!files || files.length === 0) return;
          // Context handles session binding internally
          uploadFiles(Array.from(files));
          e.target.value = "";
        },
        [uploadFiles]
      );

      const handlePaste = useCallback(
        (event: ClipboardEvent) => {
          if (disabled) return;
          const pastedFiles = getPastedFilesIfNoText(event.clipboardData);
          if (pastedFiles.length > 0) {
            event.preventDefault();
            uploadFiles(pastedFiles);
            return;
          }

          event.preventDefault();
          const text = event.clipboardData.getData("text/plain");
          if (!text) return;

          // Recreate a skill tile when pasting a lone `/<slug>` for a known
          // skill (e.g. copied from another tile), mirroring the picker flow.
          const slug = text.trim().match(/^\/(\S+)$/)?.[1];
          const skill = slug && pickerSkills.find((s) => s.slug === slug);
          if (skill) {
            insertSkillTile(skill.slug, skill.name, "");
            closeSkillPicker();
            return;
          }

          pasteText(text);
        },
        [
          disabled,
          uploadFiles,
          pasteText,
          pickerSkills,
          insertSkillTile,
          closeSkillPicker,
        ]
      );

      const handleSubmit = useCallback(() => {
        // File uploads / sandbox init / a pending interrupt are hard blockers
        // regardless of queueing — keep this in sync with `canSubmit` so the
        // keyboard (Enter) path can't bypass what the button disables.
        if (
          disabled ||
          hasUploadingFiles ||
          sandboxInitializing ||
          isInterrupting
        )
          return;

        const text = message.trim();

        // While streaming, queue the message; the parent auto-sends it later.
        if (isRunning) {
          if (onQueueMessage && text && queue.length < MAX_QUEUED_MESSAGES) {
            onQueueMessage(text);
            clearMessage();
          }
          return;
        }

        const hasFiles = currentMessageFiles.length > 0;
        if (text) {
          onSubmit(text, currentMessageFiles);
          clearMessage();
          clearFiles({ suppressRefetch: true });
        } else if (hasFiles) {
          clearFiles({ suppressRefetch: true });
        }
      }, [
        message,
        disabled,
        isRunning,
        isInterrupting,
        hasUploadingFiles,
        sandboxInitializing,
        onSubmit,
        onQueueMessage,
        queue,
        currentMessageFiles,
        clearFiles,
        clearMessage,
      ]);

      const handleKeyDown = useCallback(
        (event: KeyboardEvent<HTMLDivElement>) => {
          // Shift+Enter falls through to browser default (inserts <br>).
          const isSubmitEnter =
            event.key === "Enter" &&
            !event.shiftKey &&
            !event.nativeEvent.isComposing;

          // Enter on an arrow-selected skill tile opens its info popover.
          if (isSubmitEnter) {
            const selected = inputRef.current?.querySelector(
              '[data-rich-tile][data-tile-type="skill"].rich-input-tile-selected'
            ) as HTMLElement | null;
            if (selected) {
              event.preventDefault();
              openSkillInfo(selected);
              return;
            }
          }
          // Queue nav owns keys while a message is highlighted, so it must run
          // before tile handling (whose Backspace guard would otherwise win).
          if (queueEnabled && queueNav.handleKeyDown(event)) return;
          if (handleTileKeyDown(event)) return;

          if (isSubmitEnter) {
            event.preventDefault();
            handleSubmit();
          }
        },
        [handleSubmit, handleTileKeyDown, queueEnabled, queueNav, openSkillInfo]
      );

      const canSubmit =
        message.trim().length > 0 &&
        !disabled &&
        !hasUploadingFiles &&
        !sandboxInitializing &&
        !isInterrupting &&
        (!isRunning || (queueEnabled && queue.length < MAX_QUEUED_MESSAGES));

      // The Stop control + double-Esc shortcut are live only while a turn is
      // streaming and no popover is claiming Esc for itself.
      const interruptible = !!onInterrupt && isRunning;
      const handleInterrupt = useCallback(() => {
        if (interruptible && !isInterrupting) onInterrupt?.();
      }, [interruptible, isInterrupting, onInterrupt]);
      const { armed } = useDoubleEscapeInterrupt({
        enabled:
          interruptible &&
          !isInterrupting &&
          !session.open &&
          !tilePopover &&
          !skillInfo,
        onInterrupt: handleInterrupt,
      });

      return (
        <Disabled disabled={disabled}>
          {queueEnabled && (
            <QueuedMessageBar
              messages={queue}
              highlightedIndex={queueNav.highlightedIndex}
              awaitingPreferredSelection={false}
              onDiscard={(index) => onRemoveQueuedMessage?.(index)}
              onHighlight={queueNav.setHighlightedIndex}
            />
          )}
          <div
            ref={containerRef}
            className={cn(
              "w-full flex flex-col shadow-01 bg-background-neutral-00",
              noBottomRounding ? "rounded-t-16 rounded-b-none" : "rounded-16"
            )}
          >
            {/* Hidden file input */}
            <input
              ref={fileInputRef}
              type="file"
              className="hidden"
              multiple
              onChange={handleFileSelect}
            />

            {/* Attached Files */}
            {currentMessageFiles.length > 0 && (
              <div className="p-2 rounded-t-16 flex flex-wrap gap-1">
                {currentMessageFiles.map((file) => (
                  <BuildFileCard
                    key={file.id}
                    file={file}
                    onRemove={removeFile}
                  />
                ))}
              </div>
            )}

            {/* Input area */}
            <div ref={inputWrapperRef} className="flex-1 overflow-hidden">
              <div
                ref={inputRef}
                contentEditable={!disabled}
                suppressContentEditableWarning
                onPaste={handlePaste}
                onInput={handleEnhancedInput}
                onCompositionStart={handleCompositionStart}
                onCompositionEnd={handleCompositionEnd}
                onKeyDown={handleKeyDown}
                onKeyUp={handleSelectionChange}
                onMouseUp={handleSelectionChange}
                onBlur={() => queueNav.setHighlightedIndex(null)}
                className={cn(
                  "w-full",
                  "h-full",
                  "min-h-[44px]",
                  "outline-hidden",
                  "bg-transparent",
                  "whitespace-pre-wrap",
                  "wrap-break-word",
                  "overscroll-contain",
                  "overflow-y-auto",
                  "px-3",
                  "pb-2",
                  "pt-3"
                )}
                tabIndex={disabled ? -1 : 0}
                style={{
                  scrollbarWidth: "thin",
                  scrollbarColor: "var(--border-02) transparent",
                }}
                role="textbox"
                aria-label="Message input"
                aria-multiline={true}
                aria-disabled={disabled}
                aria-placeholder={placeholder}
                data-placeholder={placeholder}
                data-empty={!message ? "" : undefined}
                onCopy={handleCopy}
                onCut={handleCut}
                onMouseDown={handleTileMouseDown}
                onClick={handleInputClick}
              />
            </div>

            {/* Bottom controls */}
            <div className="flex justify-between items-center w-full p-1 min-h-[40px]">
              {/* Bottom left controls */}
              <div className="flex flex-row items-center gap-2">
                {/* (+) button for file upload */}
                <Button
                  disabled={disabled}
                  icon={SvgPaperclip}
                  tooltip="Attach Files"
                  prominence="tertiary"
                  onClick={() => fileInputRef.current?.click()}
                />
                {/* Streaming-only: teaches the double-Esc interrupt. */}
                {interruptible && (
                  <InterruptHint armed={armed} interrupting={isInterrupting} />
                )}
                {/* Queued messages-only: teaches the Up arrow to edit queued message.*/}
                {!message && queueEnabled && queue.length > 0 && (
                  <>
                    {interruptible && (
                      <Text font="secondary-body" color="text-02">
                        ·
                      </Text>
                    )}
                    <div className="flex items-center gap-1 select-none">
                      <Keycap>↑</Keycap>
                      <Text font="secondary-body" color="text-02">
                        to edit queued messages
                      </Text>
                    </div>
                  </>
                )}
              </div>

              {/* Bottom right controls */}
              <div className="flex flex-row items-center gap-1">
                {/* Stop: inserts to the LEFT of the fixed send button while
                    streaming. The first Esc "arms" it with a subtle neutral fill. */}
                <div
                  className={cn(
                    "overflow-hidden transition-[width,opacity] duration-150 ease-out motion-reduce:transition-none",
                    interruptible
                      ? "w-9 opacity-100"
                      : "w-0 opacity-0 pointer-events-none"
                  )}
                >
                  <IconButton
                    main
                    tertiary
                    icon={isInterrupting ? SvgLoader : SvgStop}
                    iconClassName={isInterrupting ? "animate-spin" : undefined}
                    className={cn(
                      "border-[1.5px] border-border-02",
                      armed && "bg-background-tint-02!"
                    )}
                    disabled={!interruptible || isInterrupting}
                    onClick={handleInterrupt}
                    tooltip="Stop · esc esc"
                    aria-label="Stop generating"
                  />
                </div>
                {/* Submit button — fixed rightmost in every state. */}
                {/* TODO(@raunakab): migrate to opal Button once className/iconClassName is resolved */}
                <IconButton
                  icon={sandboxInitializing ? SvgLoader : SvgArrowUp}
                  onClick={handleSubmit}
                  disabled={!canSubmit}
                  tooltip={
                    sandboxInitializing
                      ? "Initializing sandbox..."
                      : isRunning
                        ? "Queue message"
                        : "Send"
                  }
                  aria-label={isRunning ? "Queue message" : "Send"}
                  iconClassName={
                    sandboxInitializing ? "animate-spin" : undefined
                  }
                />
              </div>
            </div>
          </div>
          {tilePopover && (
            <PasteTilePopover
              text={tilePopover.text}
              tileElement={tilePopover.tile}
              onDismiss={dismissTilePopover}
              onTextChange={updateTileText}
            />
          )}
          <SkillPickerPopover
            open={session.open}
            anchorRect={anchorRect}
            query={session.query}
            skills={pickerSkills}
            onSelect={handleSkillPickerSelect}
            onClose={dismissSkillPicker}
          />
          {skillInfo && (
            <SkillInfoPopover
              name={skillInfo.name}
              description={skillInfo.description}
              tileElement={skillInfo.tile}
              onDismiss={dismissSkillInfo}
            />
          )}
        </Disabled>
      );
    }
  )
);

InputBar.displayName = "InputBar";

export default InputBar;
