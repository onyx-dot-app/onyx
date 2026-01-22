"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { cn, isImageFile } from "@/lib/utils";
import {
  useUploadFilesContext,
  BuildFile,
  UploadFileStatus,
} from "@/app/build/contexts/UploadFilesContext";
import { useDemoDataEnabled } from "@/app/build/hooks/useBuildSessionStore";
import IconButton from "@/refresh-components/buttons/IconButton";
import SelectButton from "@/refresh-components/buttons/SelectButton";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import {
  SvgArrowUp,
  SvgFileText,
  SvgImage,
  SvgLoader,
  SvgX,
  SvgPaperclip,
  SvgOrganization,
} from "@opal/icons";

const MAX_INPUT_HEIGHT = 200;

export interface InputBarHandle {
  reset: () => void;
  focus: () => void;
}

export interface InputBarProps {
  onSubmit: (
    message: string,
    files: BuildFile[],
    demoDataEnabled: boolean
  ) => void;
  isRunning: boolean;
  disabled?: boolean;
  placeholder?: string;
  /** Session ID for immediate file uploads. If provided, files upload immediately when attached. */
  sessionId?: string;
  /** When true, shows spinner on send button with "Initializing sandbox..." tooltip */
  sandboxInitializing?: boolean;
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
        sessionId,
        sandboxInitializing = false,
      },
      ref
    ) => {
      const router = useRouter();
      const demoDataEnabled = useDemoDataEnabled();
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
          // Pass sessionId so files upload immediately if session exists
          uploadFiles(Array.from(files), sessionId);
          e.target.value = "";
        },
        [uploadFiles, sessionId]
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
              // Pass sessionId so files upload immediately if session exists
              uploadFiles(pastedFiles, sessionId);
            }
          }
        },
        [uploadFiles, sessionId]
      );

      const handleInputChange = useCallback(
        (event: React.ChangeEvent<HTMLTextAreaElement>) => {
          setMessage(event.target.value);
        },
        []
      );

      const handleSubmit = useCallback(() => {
        if (
          !message.trim() ||
          disabled ||
          isRunning ||
          hasUploadingFiles ||
          sandboxInitializing
        )
          return;
        onSubmit(message.trim(), currentMessageFiles, demoDataEnabled);
        setMessage("");
        clearFiles();
      }, [
        message,
        disabled,
        isRunning,
        hasUploadingFiles,
        sandboxInitializing,
        onSubmit,
        currentMessageFiles,
        clearFiles,
        demoDataEnabled,
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
        !hasUploadingFiles &&
        !sandboxInitializing;

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
                  onRemove={(id) => removeFile(id, sessionId)}
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
            <div className="flex flex-row items-center gap-1">
              {/* (+) button for file upload */}
              <IconButton
                icon={SvgPaperclip}
                tooltip="Attach Files"
                tertiary
                disabled={disabled}
                onClick={() => fileInputRef.current?.click()}
              />
              {/* Demo Data indicator pill */}
              <SimpleTooltip
                tooltip="Switch to your data in the Configure panel!"
                side="top"
              >
                <span>
                  <SelectButton
                    leftIcon={SvgOrganization}
                    engaged={demoDataEnabled}
                    action
                    folded
                    disabled={disabled}
                    onClick={() => router.push("/build/v1/configure")}
                    className="bg-action-link-01"
                  >
                    Demo Data
                  </SelectButton>
                </span>
              </SimpleTooltip>
            </div>

            {/* Bottom right controls */}
            <div className="flex flex-row items-center gap-1">
              {/* Submit button */}
              <IconButton
                icon={sandboxInitializing ? SvgLoader : SvgArrowUp}
                onClick={handleSubmit}
                disabled={!canSubmit}
                tooltip={
                  sandboxInitializing ? "Initializing sandbox..." : "Send"
                }
                iconClassName={sandboxInitializing ? "animate-spin" : undefined}
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
