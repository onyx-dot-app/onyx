"use client";

import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { cn, isImageFile } from "@/lib/utils";
import { LlmManager } from "@/lib/hooks";
import {
  useUploadFilesContext,
  BuildFile,
  UploadFileStatus,
} from "@/app/build/contexts/UploadFilesContext";
import IconButton from "@/refresh-components/buttons/IconButton";
import LLMPopover from "@/refresh-components/popovers/LLMPopover";
import {
  SvgArrowUp,
  SvgPlusCircle,
  SvgFileText,
  SvgImage,
  SvgLoader,
  SvgX,
  SvgPaperclip,
} from "@opal/icons";

const MAX_INPUT_HEIGHT = 200;

export interface InputBarHandle {
  reset: () => void;
  focus: () => void;
}

export interface InputBarProps {
  onSubmit: (message: string, files: BuildFile[]) => void;
  isRunning: boolean;
  disabled?: boolean;
  placeholder?: string;
  llmManager: LlmManager;
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

  return (
    <div
      className={cn(
        "flex items-center gap-1.5 px-2 py-1 rounded-08",
        "bg-background-neutral-01 border border-border-01",
        "text-sm text-text-04"
      )}
    >
      {isUploading ? (
        <SvgLoader className="h-4 w-4 animate-spin text-text-03" />
      ) : isImage ? (
        <SvgImage className="h-4 w-4 text-text-03" />
      ) : (
        <SvgFileText className="h-4 w-4 text-text-03" />
      )}
      <span className="max-w-[120px] truncate">{file.name}</span>
      <button
        onClick={() => onRemove(file.id)}
        className="ml-1 p-0.5 hover:bg-background-neutral-02 rounded"
      >
        <SvgX className="h-3 w-3 text-text-03" />
      </button>
    </div>
  );
}

const InputBar = React.memo(
  React.forwardRef<InputBarHandle, InputBarProps>(
    (
      {
        onSubmit,
        isRunning,
        disabled = false,
        placeholder = "Describe your task...",
        llmManager,
      },
      ref
    ) => {
      const [message, setMessage] = useState("");
      const textAreaRef = useRef<HTMLTextAreaElement>(null);
      const containerRef = useRef<HTMLDivElement>(null);
      const fileInputRef = useRef<HTMLInputElement>(null);

      const {
        currentMessageFiles,
        uploadFiles,
        removeFile,
        clearFiles,
        hasUploadingFiles,
      } = useUploadFilesContext();

      // Expose reset and focus methods to parent via ref
      React.useImperativeHandle(ref, () => ({
        reset: () => {
          setMessage("");
          clearFiles();
        },
        focus: () => {
          textAreaRef.current?.focus();
        },
      }));

      const shouldCompactImages = useMemo(() => {
        return currentMessageFiles.length > 1;
      }, [currentMessageFiles]);

      // Auto-resize textarea based on content
      useEffect(() => {
        const textarea = textAreaRef.current;
        if (textarea) {
          textarea.style.height = "0px";
          textarea.style.height = `${Math.min(
            textarea.scrollHeight,
            MAX_INPUT_HEIGHT
          )}px`;
        }
      }, [message]);

      // Auto-focus on mount
      useEffect(() => {
        textAreaRef.current?.focus();
      }, []);

      const handleFileSelect = useCallback(
        async (e: React.ChangeEvent<HTMLInputElement>) => {
          const files = e.target.files;
          if (!files || files.length === 0) return;
          uploadFiles(Array.from(files));
          e.target.value = "";
        },
        [uploadFiles]
      );

      const handlePaste = useCallback(
        (event: React.ClipboardEvent) => {
          const items = event.clipboardData?.items;
          if (items) {
            const pastedFiles: File[] = [];
            for (let i = 0; i < items.length; i++) {
              const item = items[i];
              if (item && item.kind === "file") {
                const file = item.getAsFile();
                if (file) pastedFiles.push(file);
              }
            }
            if (pastedFiles.length > 0) {
              event.preventDefault();
              uploadFiles(pastedFiles);
            }
          }
        },
        [uploadFiles]
      );

      const handleInputChange = useCallback(
        (event: React.ChangeEvent<HTMLTextAreaElement>) => {
          setMessage(event.target.value);
        },
        []
      );

      const handleSubmit = useCallback(() => {
        if (!message.trim() || disabled || isRunning || hasUploadingFiles)
          return;
        onSubmit(message.trim(), currentMessageFiles);
        setMessage("");
        clearFiles();
      }, [
        message,
        disabled,
        isRunning,
        hasUploadingFiles,
        onSubmit,
        currentMessageFiles,
        clearFiles,
      ]);

      const handleKeyDown = useCallback(
        (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
          if (
            event.key === "Enter" &&
            !event.shiftKey &&
            !(event.nativeEvent as any).isComposing
          ) {
            event.preventDefault();
            handleSubmit();
          }
        },
        [handleSubmit]
      );

      const canSubmit =
        message.trim().length > 0 &&
        !disabled &&
        !isRunning &&
        !hasUploadingFiles;

      return (
        <div
          ref={containerRef}
          className={cn(
            "w-full flex flex-col shadow-01 bg-background-neutral-00 rounded-16",
            disabled && "opacity-50 cursor-not-allowed pointer-events-none"
          )}
          aria-disabled={disabled}
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
          <textarea
            onPaste={handlePaste}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            ref={textAreaRef}
            className={cn(
              "w-full",
              "h-[44px]",
              "outline-none",
              "bg-transparent",
              "resize-none",
              "placeholder:text-text-03",
              "whitespace-pre-wrap",
              "break-word",
              "overscroll-contain",
              "overflow-y-auto",
              "px-3",
              "pb-2",
              "pt-3"
            )}
            autoFocus
            style={{ scrollbarWidth: "thin" }}
            role="textarea"
            aria-multiline
            placeholder={placeholder}
            value={message}
            disabled={disabled}
          />

          {/* Bottom controls */}
          <div className="flex justify-between items-center w-full p-1 min-h-[40px]">
            {/* Bottom left controls */}
            <div className="flex flex-row items-center">
              {/* (+) button for file upload */}
              <IconButton
                icon={SvgPaperclip}
                tooltip="Attach Files"
                tertiary
                disabled={disabled}
                onClick={() => fileInputRef.current?.click()}
              />
            </div>

            {/* Bottom right controls */}
            <div className="flex flex-row items-center gap-1">
              {/* LLM popover */}
              <div className={cn(llmManager.isLoadingProviders && "invisible")}>
                <LLMPopover llmManager={llmManager} disabled={disabled} />
              </div>

              {/* Submit button */}
              <IconButton
                icon={SvgArrowUp}
                onClick={handleSubmit}
                disabled={!canSubmit}
                tooltip="Send"
              />
            </div>
          </div>
        </div>
      );
    }
  )
);

InputBar.displayName = "InputBar";

export default InputBar;
