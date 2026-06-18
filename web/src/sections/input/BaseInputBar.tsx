"use client";

import {
  forwardRef,
  memo,
  useCallback,
  useImperativeHandle,
  useRef,
  type ClipboardEvent,
  type KeyboardEvent,
  type ReactNode,
  type SyntheticEvent,
} from "react";
import { getPastedFilesIfNoText } from "@/lib/clipboard";
import { deleteTokenBeforeCursor, getTextContent } from "@/lib/contentEditable";
import PasteTilePopover from "@/sections/input/PasteTilePopover";
import { cn } from "@opal/utils";
import { Disabled } from "@opal/core";
import IconButton from "@/refresh-components/buttons/IconButton";
import { Text } from "@opal/components";
import { SvgArrowUp, SvgLoader, SvgStop } from "@opal/icons";
import Keycap from "@/refresh-components/Keycap";
import { useContentEditable } from "@/hooks/useContentEditable";
import QueuedMessageBar from "@/sections/input/QueuedMessageBar";
import { handleInputNavKeys } from "@/sections/input/inputBarKeys";
import { useQueuedMessageNavigation } from "@/hooks/useQueuedMessageNavigation";
import {
  EMPTY_QUEUED_MESSAGES,
  MAX_QUEUED_MESSAGES,
  type QueuedMessage,
} from "@/app/app/interfaces";

export interface BaseInputBarHandle {
  reset: () => void;
  focus: () => void;
  setMessage: (message: string) => void;
  pasteText: (text: string) => void;
  getTextBeforeCursor: () => string | null;
  getCaretRect: () => DOMRect | null;
  /** Delete `token` immediately before the caret (e.g. `"/pptx"`). */
  deleteBeforeToken: (token: string) => boolean;
}

export interface BaseInputBarProps {
  onSubmit: (message: string) => void;
  isRunning: boolean;
  disabled?: boolean;
  placeholder?: string;
  noBottomRounding?: boolean;
  pasteTilesEnabled?: boolean;
  sandboxInitializing?: boolean;
  /** Blocks submit without the disabled visual (e.g. files still uploading). */
  submitBlocked?: boolean;

  queuedMessages?: readonly QueuedMessage[];
  onQueueMessage?: (text: string) => void;
  onRemoveQueuedMessage?: (index: number) => void;

  onInterrupt?: () => void;
  isInterrupting?: boolean;

  topSlot?: ReactNode;
  bottomLeftSlot?: ReactNode;
  /** Rendered in the right control group, left of Stop/Send (e.g. a mic button). */
  bottomRightSlot?: ReactNode;

  /** Return true to consume the pasted text (skips pasteText). */
  onPasteText?: (text: string) => boolean;
  onPasteFiles?: (files: File[]) => void;
  onInputCallback?: () => void;
  onSelectionChange?: () => void;
}

const BaseInputBar = memo(
  forwardRef<BaseInputBarHandle, BaseInputBarProps>(
    (
      {
        onSubmit,
        isRunning,
        disabled = false,
        placeholder = "Describe your task...",
        noBottomRounding = false,
        pasteTilesEnabled = false,
        sandboxInitializing = false,
        submitBlocked = false,
        queuedMessages,
        onQueueMessage,
        onRemoveQueuedMessage,
        onInterrupt,
        isInterrupting = false,
        topSlot,
        bottomLeftSlot,
        bottomRightSlot,
        onPasteText,
        onPasteFiles,
        onInputCallback,
        onSelectionChange,
      },
      ref
    ) => {
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
        pasteExpandHintVisible,
        handleCopy,
        handleCut,
        setCursorToEnd,
        handleTileMouseDown,
        handleTileClick,
        handleTileKeyDown,
        tilePopover,
        dismissTilePopover,
        updateTileText,
        expandTile,
      } = useContentEditable({
        wrapperRef: inputWrapperRef,
        pasteTilesEnabled,
        disabled,
      });

      const queueNav = useQueuedMessageNavigation({
        messages: queue,
        inputIsEmpty: !message,
        onRemove: (index) => onRemoveQueuedMessage?.(index),
        onEdit: setMessage,
      });

      useImperativeHandle(ref, () => ({
        reset: () => {
          clearMessage();
        },
        focus: () => {
          inputRef.current?.focus();
          setCursorToEnd();
        },
        setMessage: (msg: string) => setMessage(msg),
        pasteText: (text: string) => pasteText(text),
        getTextBeforeCursor: (): string | null => {
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
        },
        getCaretRect: (): DOMRect | null => {
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
        },
        deleteBeforeToken: (token: string): boolean => {
          const el = inputRef.current;
          if (!el) return false;
          return deleteTokenBeforeCursor(el, token);
        },
      }));

      const handlePaste = useCallback(
        (event: ClipboardEvent) => {
          if (disabled) return;
          const pastedFiles = getPastedFilesIfNoText(event.clipboardData);
          if (pastedFiles.length > 0) {
            event.preventDefault();
            onPasteFiles?.(pastedFiles);
            return;
          }
          event.preventDefault();
          const text = event.clipboardData.getData("text/plain");
          if (!text) return;
          if (onPasteText?.(text)) return;
          pasteText(text);
        },
        [disabled, onPasteFiles, onPasteText, pasteText]
      );

      const handleSubmit = useCallback(() => {
        if (disabled || submitBlocked || sandboxInitializing || isInterrupting)
          return;
        const text = message.trim();
        if (isRunning) {
          if (onQueueMessage && text && queue.length < MAX_QUEUED_MESSAGES) {
            onQueueMessage(text);
            clearMessage();
          }
          return;
        }
        if (text) {
          onSubmit(text);
          clearMessage();
        }
      }, [
        message,
        disabled,
        submitBlocked,
        isRunning,
        isInterrupting,
        sandboxInitializing,
        onSubmit,
        onQueueMessage,
        queue,
        clearMessage,
      ]);

      const handleInput = useCallback(
        (event: SyntheticEvent<HTMLDivElement>) => {
          onInput(event);
          onInputCallback?.();
        },
        [onInput, onInputCallback]
      );

      const handleKeyDown = useCallback(
        (event: KeyboardEvent<HTMLDivElement>) => {
          const isSubmitEnter =
            event.key === "Enter" &&
            !event.shiftKey &&
            !event.nativeEvent.isComposing;
          if (handleInputNavKeys(event, queueNav, handleTileKeyDown)) return;
          if (isSubmitEnter) {
            event.preventDefault();
            handleSubmit();
          }
        },
        [handleSubmit, handleTileKeyDown, queueNav]
      );

      const handleSelectionChange = useCallback(() => {
        onSelectionChange?.();
      }, [onSelectionChange]);

      const canSubmit =
        message.trim().length > 0 &&
        !disabled &&
        !submitBlocked &&
        !sandboxInitializing &&
        !isInterrupting &&
        (!isRunning || (queueEnabled && queue.length < MAX_QUEUED_MESSAGES));

      const interruptible = !!onInterrupt && isRunning;
      const handleInterrupt = useCallback(() => {
        if (interruptible && !isInterrupting) onInterrupt?.();
      }, [interruptible, isInterrupting, onInterrupt]);

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
            className={cn(
              "w-full flex flex-col shadow-01 bg-background-neutral-00",
              noBottomRounding ? "rounded-t-16 rounded-b-none" : "rounded-16"
            )}
          >
            {/* Slot owns its own padding so it can animate (e.g. collapse). */}
            {topSlot}

            <div ref={inputWrapperRef} className="flex-1 overflow-hidden">
              <div
                ref={inputRef}
                contentEditable={!disabled}
                suppressContentEditableWarning
                onPaste={handlePaste}
                onInput={handleInput}
                onCompositionStart={handleCompositionStart}
                onCompositionEnd={handleCompositionEnd}
                onKeyDown={handleKeyDown}
                onKeyUp={handleSelectionChange}
                onMouseUp={handleSelectionChange}
                onBlur={() => queueNav.setHighlightedIndex(null)}
                className={cn(
                  "w-full h-full min-h-[44px] outline-hidden bg-transparent",
                  "whitespace-pre-wrap wrap-break-word overscroll-contain",
                  "overflow-y-auto px-3 pb-2 pt-3"
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

            <div className="flex justify-between items-center w-full p-1 min-h-[40px]">
              <div className="flex flex-row items-center gap-2">
                {bottomLeftSlot}
                {pasteExpandHintVisible ? (
                  <div className="flex items-center gap-1 select-none">
                    <Text font="secondary-body" color="text-02">
                      Paste again to expand
                    </Text>
                  </div>
                ) : (
                  !message &&
                  queueEnabled &&
                  queue.length > 0 && (
                    <div className="flex items-center gap-1 select-none">
                      <Keycap>↑</Keycap>
                      <Text font="secondary-body" color="text-02">
                        to edit queued messages
                      </Text>
                    </div>
                  )
                )}
              </div>
              <div className="flex flex-row items-center gap-1">
                {bottomRightSlot}
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
                    className="border-[1.5px] border-border-02"
                    disabled={!interruptible || isInterrupting}
                    onClick={handleInterrupt}
                    tooltip="Stop · esc"
                    aria-label="Stop generating"
                  />
                </div>
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
              onExpand={() => expandTile(tilePopover.tile)}
            />
          )}
        </Disabled>
      );
    }
  )
);

BaseInputBar.displayName = "BaseInputBar";

export default BaseInputBar;
