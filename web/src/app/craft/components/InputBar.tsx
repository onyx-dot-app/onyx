"use client";

import {
  memo,
  forwardRef,
  useImperativeHandle,
  useCallback,
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type ClipboardEvent,
  type KeyboardEvent,
} from "react";
import { useRouter } from "next/navigation";
import { cn, isImageFile } from "@/lib/utils";
import { Disabled } from "@/refresh-components/Disabled";
import {
  useUploadFilesContext,
  BuildFile,
  UploadFileStatus,
} from "@/app/craft/contexts/UploadFilesContext";
import { useDemoDataEnabled } from "@/app/craft/hooks/useBuildSessionStore";
import { CRAFT_CONFIGURE_PATH } from "@/app/craft/v1/constants";
import IconButton from "@/refresh-components/buttons/IconButton";
import SelectButton from "@/refresh-components/buttons/SelectButton";
import { Button } from "@opal/components";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import {
  SvgArrowUp,
  SvgClock,
  SvgFileText,
  SvgImage,
  SvgLoader,
  SvgX,
  SvgPaperclip,
  SvgOrganization,
  SvgAlertCircle,
} from "@opal/icons";

const MAX_INPUT_HEIGHT = 200;

export interface InputBarHandle {
  reset: () => void;
  focus: () => void;
  setMessage: (message: string) => void;
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
  /** When true, shows spinner on send button with "Initializing sandbox..." tooltip */
  sandboxInitializing?: boolean;
  /** When true, removes bottom rounding to allow seamless connection with components below */
  noBottomRounding?: boolean;
  /** Whether this is the welcome page (no existing session in URL). Used for Demo Data pill. */
  isWelcomePage?: boolean;
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
        className="ml-1 p-0.5 hover:bg-background-neutral-02 rounded"
      >
        <SvgX className="h-3 w-3 text-text-03" />
      </button>
    </div>
  );

  // Wrap in tooltip for error or pending status
  if (isFailed && file.error) {
    return (
      <SimpleTooltip tooltip={file.error} side="top">
        {cardContent}
      </SimpleTooltip>
    );
  }

  if (isPending) {
    return (
      <SimpleTooltip tooltip="Waiting for session to be ready..." side="top">
        {cardContent}
      </SimpleTooltip>
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
        isWelcomePage = false,
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

      // Expose reset, focus, and setMessage methods to parent via ref
      useImperativeHandle(ref, () => ({
        reset: () => {
          setMessage("");
          clearFiles();
        },
        focus: () => {
          textAreaRef.current?.focus();
        },
        setMessage: (msg: string) => {
          setMessage(msg);
          // Move cursor to end after setting message
          setTimeout(() => {
            const textarea = textAreaRef.current;
            if (textarea) {
              textarea.focus();
              textarea.setSelectionRange(msg.length, msg.length);
            }
          }, 0);
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
              // Context handles session binding internally
              uploadFiles(pastedFiles);
            }
          }
        },
        [uploadFiles]
      );

      const handleInputChange = useCallback(
        (event: ChangeEvent<HTMLTextAreaElement>) => {
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
        (event: KeyboardEvent<HTMLTextAreaElement>) => {
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
                <Button
                  icon={SvgPaperclip}
                  tooltip="Attach Files"
                  prominence="tertiary"
                  disabled={disabled}
                  onClick={() => fileInputRef.current?.click()}
                />
                {/* Demo Data indicator pill - only show on welcome page (no session) when demo data is enabled */}
                {demoDataEnabled && isWelcomePage && (
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
                        onClick={() => router.push(CRAFT_CONFIGURE_PATH)}
                        className="bg-action-link-01"
                      >
                        Demo Data Active
                      </SelectButton>
                    </span>
                  </SimpleTooltip>
                )}
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
                  iconClassName={
                    sandboxInitializing ? "animate-spin" : undefined
                  }
                />
              </div>
            </div>
          </div>
        </Disabled>
      );
    }
  )
);

InputBar.displayName = "InputBar";

export default InputBar;
