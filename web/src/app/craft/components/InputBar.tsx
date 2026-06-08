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
  type SyntheticEvent,
} from "react";
import { getPastedFilesIfNoText } from "@/lib/clipboard";
import { isImageFile } from "@/lib/utils";
import PasteTilePopover from "@/sections/input/PasteTilePopover";
import SkillPickerPopover from "@/sections/input/SkillPickerPopover";
import { cn } from "@opal/utils";
import { Disabled } from "@opal/core";
import {
  useUploadFilesContext,
  BuildFile,
  UploadFileStatus,
} from "@/app/craft/contexts/UploadFilesContext";
import IconButton from "@/refresh-components/buttons/IconButton";
import { Button, Tooltip } from "@opal/components";
import {
  SvgArrowUp,
  SvgClock,
  SvgFileText,
  SvgImage,
  SvgLoader,
  SvgX,
  SvgPaperclip,
  SvgAlertCircle,
} from "@opal/icons";
import { useContentEditable } from "@/hooks/useContentEditable";
import { useUser } from "@/providers/UserProvider";
import useUserSkills from "@/hooks/useUserSkills";
import { detectSlashTrigger, toPickerSkills } from "@/lib/skills/picker";
import { getTextContent } from "@/lib/contentEditable";

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
      <span
        className={cn(
          "max-w-[120px] truncate",
          isFailed && "text-status-error-02"
        )}
      >
        {file.name}
      </span>
      <button
        onClick={() => onRemove(file.id)}
        className="ml-1 p-0.5 hover:bg-background-neutral-02 rounded-sm"
      >
        <SvgX className="h-3 w-3 text-text-03" />
      </button>
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
      },
      ref
    ) => {
      const { user } = useUser();
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
        pasteTilesEnabled: user?.preferences?.paste_as_tile ?? false,
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

      // `/` skill picker state. The picker watches contentEditable input,
      // shows accessible skills, and on select replaces the `/<query>` token
      // with `/<slug> `.
      const { data: skillsData } = useUserSkills();
      const pickerSkills = useMemo(
        () => toPickerSkills(skillsData),
        [skillsData]
      );
      const [skillPicker, setSkillPicker] = useState<{
        open: boolean;
        anchorRect: DOMRect | null;
        query: string;
        slashIndex: number;
      }>({ open: false, anchorRect: null, query: "", slashIndex: -1 });

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

      const evaluateSkillPicker = useCallback(() => {
        const textBefore = getTextBeforeCursor();
        if (textBefore === null) {
          setSkillPicker((s) => (s.open ? { ...s, open: false } : s));
          return;
        }
        const trigger = detectSlashTrigger(textBefore);
        if (!trigger) {
          setSkillPicker((s) => (s.open ? { ...s, open: false } : s));
          return;
        }
        setSkillPicker({
          open: true,
          anchorRect: getCaretRect(),
          query: trigger.query,
          slashIndex: trigger.slashIndex,
        });
      }, [getCaretRect, getTextBeforeCursor]);

      const handleEnhancedInput = useCallback(
        (event: SyntheticEvent<HTMLDivElement>) => {
          onInput(event);
          evaluateSkillPicker();
        },
        [onInput, evaluateSkillPicker]
      );

      // Re-evaluate the slash trigger when the caret moves without input
      // (arrow keys, Home/End, mouse clicks). Without this, the picker can
      // hold a stale `slashIndex`/`query` from a previous position and
      // replace the wrong text on select.
      const handleSelectionChange = useCallback(() => {
        evaluateSkillPicker();
      }, [evaluateSkillPicker]);

      const closeSkillPicker = useCallback(() => {
        setSkillPicker((s) => ({ ...s, open: false }));
      }, []);

      const handleSkillPickerSelect = useCallback(
        (slug: string) => {
          setSkillPicker((prev) => {
            if (!prev.open) return prev;
            const replacement = `/${slug} `;
            const newText =
              message.slice(0, prev.slashIndex) +
              replacement +
              message.slice(prev.slashIndex + 1 + prev.query.length);
            setMessage(newText);
            return { ...prev, open: false };
          });
        },
        [message, setMessage]
      );

      useImperativeHandle(ref, () => ({
        reset: () => {
          clearMessage();
          clearFiles();
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

          pasteText(text);
        },
        [disabled, uploadFiles, pasteText]
      );

      const handleSubmit = useCallback(() => {
        if (disabled || isRunning || hasUploadingFiles || sandboxInitializing)
          return;

        const hasMessage = message.trim().length > 0;
        const hasFiles = currentMessageFiles.length > 0;

        if (hasMessage) {
          onSubmit(message.trim(), currentMessageFiles);
          clearMessage();
          clearFiles({ suppressRefetch: true });
        } else if (hasFiles) {
          clearFiles({ suppressRefetch: true });
        }
      }, [
        message,
        disabled,
        isRunning,
        hasUploadingFiles,
        sandboxInitializing,
        onSubmit,
        currentMessageFiles,
        clearFiles,
        clearMessage,
      ]);

      const handleKeyDown = useCallback(
        (event: KeyboardEvent<HTMLDivElement>) => {
          if (handleTileKeyDown(event)) return;

          // Shift+Enter falls through to browser default: inserts <br>
          if (
            event.key === "Enter" &&
            !event.shiftKey &&
            !(event.nativeEvent as any).isComposing
          ) {
            event.preventDefault();
            handleSubmit();
          }
        },
        [handleSubmit, handleTileKeyDown]
      );

      const canSubmit =
        message.trim().length > 0 &&
        !disabled &&
        !isRunning &&
        !hasUploadingFiles &&
        !sandboxInitializing;

      return (
        <Disabled disabled={disabled}>
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
              accept="*/*"
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
                onClick={handleTileClick}
              />
            </div>

            {/* Bottom controls */}
            <div className="flex justify-between items-center w-full p-1 min-h-[40px]">
              {/* Bottom left controls */}
              <div className="flex flex-row items-center gap-1">
                {/* (+) button for file upload */}
                <Button
                  disabled={disabled}
                  icon={SvgPaperclip}
                  tooltip="Attach Files"
                  prominence="tertiary"
                  onClick={() => fileInputRef.current?.click()}
                />
              </div>

              {/* Bottom right controls */}
              <div className="flex flex-row items-center gap-1">
                {/* Submit button */}
                {/* TODO(@raunakab): migrate to opal Button once className/iconClassName is resolved */}
                <IconButton
                  icon={sandboxInitializing ? SvgLoader : SvgArrowUp}
                  onClick={handleSubmit}
                  disabled={!canSubmit}
                  tooltip={
                    sandboxInitializing ? "Initializing sandbox..." : "Send"
                  }
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
            open={skillPicker.open}
            anchorRect={skillPicker.anchorRect}
            query={skillPicker.query}
            skills={pickerSkills}
            onSelect={handleSkillPickerSelect}
            onClose={closeSkillPicker}
          />
        </Disabled>
      );
    }
  )
);

InputBar.displayName = "InputBar";

export default InputBar;
