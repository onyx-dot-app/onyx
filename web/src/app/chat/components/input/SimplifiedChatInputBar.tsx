import React, { useEffect } from "react";
import { FiPlusCircle } from "react-icons/fi";
import { ChatInputOption } from "./ChatInputOption";
import { FilterManager } from "@/lib/hooks";
import { ChatFileType, FileDescriptor } from "@/app/chat/interfaces";
import {
  InputBarPreview,
  InputBarPreviewImageProvider,
} from "@/app/chat/components/files/InputBarPreview";
import { SendIcon } from "@/components/icons/icons";
import { HorizontalSourceSelector } from "@/components/search/filtering/HorizontalSourceSelector";
import { Tag } from "@/lib/types";

const MAX_INPUT_HEIGHT = 200;

interface ChatInputBarProps {
  message: string;
  setMessage: (message: string) => void;
  onSubmit: () => void;
  files: FileDescriptor[];
  setFiles: (files: FileDescriptor[]) => void;
  handleFileUpload: (files: File[]) => void;
  textAreaRef: React.RefObject<HTMLTextAreaElement>;
  filterManager?: FilterManager;
  existingSources: string[];
  availableDocumentSets: { name: string }[];
  availableTags: Tag[];
}

export function SimplifiedChatInputBar({
  message,
  setMessage,
  onSubmit,
  files,
  setFiles,
  handleFileUpload,
  textAreaRef,
  filterManager,
  existingSources,
  availableDocumentSets,
  availableTags,
}: ChatInputBarProps) {
  useEffect(() => {
    const textarea = textAreaRef.current;
    if (textarea) {
      textarea.style.height = "0px";
      textarea.style.height = `${Math.min(
        textarea.scrollHeight,
        MAX_INPUT_HEIGHT
      )}px`;
    }
  }, [message, textAreaRef]);

  const handlePaste = (event: React.ClipboardEvent) => {
    const items = event.clipboardData?.items;
    if (items) {
      const pastedFiles = [];
      for (let i = 0; i < items.length; i++) {
        const item = items[i];
        if (item && item.kind === "file") {
          const file = item.getAsFile();
          if (file) pastedFiles.push(file);
        }
      }
      if (pastedFiles.length > 0) {
        event.preventDefault();
        handleFileUpload(pastedFiles);
      }
    }
  };

  const handleInputChange = (event: React.ChangeEvent<HTMLTextAreaElement>) => {
    const text = event.target.value;
    setMessage(text);
  };

  return (
    <div
      id="onyx-chat-input"
      className="
            w-full
            relative
            mx-auto
          "
    >
      <div
        className="
              opacity-100
              w-full
              h-fit
              flex
              flex-col
              border
              border-background-200
              rounded-lg
              relative
              text-text-chatbar
              bg-white
              [&:has(textarea:focus)]::ring-1
              [&:has(textarea:focus)]::ring-black
            "
      >
        {files.length > 0 && (
          <div className="flex gap-x-2 px-2 pt-2">
            <div className="flex gap-x-1 px-2 overflow-visible overflow-x-scroll items-end miniscroll">
              {files.map((file) => (
                <div className="flex-none" key={file.id}>
                  {file.type === ChatFileType.IMAGE ? (
                    <InputBarPreviewImageProvider
                      file={file}
                      onDelete={() => {
                        setFiles(
                          files.filter(
                            (fileInFilter) => fileInFilter.id !== file.id
                          )
                        );
                      }}
                      isUploading={file.isUploading || false}
                    />
                  ) : (
                    <InputBarPreview
                      file={file}
                      onDelete={() => {
                        setFiles(
                          files.filter(
                            (fileInFilter) => fileInFilter.id !== file.id
                          )
                        );
                      }}
                      isUploading={file.isUploading || false}
                    />
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        <textarea
          onPaste={handlePaste}
          onChange={handleInputChange}
          ref={textAreaRef}
          className={`
                m-0
                w-full
                shrink
                resize-none
                rounded-lg
                border-0
                bg-white
                placeholder:text-text-chatbar-subtle
                ${
                  textAreaRef.current &&
                  textAreaRef.current.scrollHeight > MAX_INPUT_HEIGHT
                    ? "overflow-y-auto mt-2"
                    : ""
                }
                whitespace-normal
                break-word
                overscroll-contain
                outline-none
                placeholder-subtle
                resize-none
                px-5
                py-4
                h-14
              `}
          autoFocus
          style={{ scrollbarWidth: "thin" }}
          role="textarea"
          aria-multiline
          placeholder="Ask me anything..."
          value={message}
          onKeyDown={(event) => {
            if (
              event.key === "Enter" &&
              !event.shiftKey &&
              !(event.nativeEvent as any).isComposing
            ) {
              event.preventDefault();
              if (message) {
                onSubmit();
              }
            }
          }}
          suppressContentEditableWarning={true}
        />
        <div className="flex items-center space-x-3 mr-12 px-4 pb-2">
          <ChatInputOption
            flexPriority="stiff"
            name="File"
            Icon={FiPlusCircle}
            onClick={() => {
              const input = document.createElement("input");
              input.type = "file";
              input.multiple = true; // Allow multiple files
              input.onchange = (event: any) => {
                const selectedFiles = Array.from(
                  event?.target?.files || []
                ) as File[];
                if (selectedFiles.length > 0) {
                  handleFileUpload(selectedFiles);
                }
              };
              input.click();
            }}
          />

          {filterManager && (
            <HorizontalSourceSelector
              timeRange={filterManager.timeRange}
              setTimeRange={filterManager.setTimeRange}
              selectedSources={filterManager.selectedSources}
              setSelectedSources={filterManager.setSelectedSources}
              selectedDocumentSets={filterManager.selectedDocumentSets}
              setSelectedDocumentSets={filterManager.setSelectedDocumentSets}
              selectedTags={filterManager.selectedTags}
              setSelectedTags={filterManager.setSelectedTags}
              existingSources={existingSources}
              availableDocumentSets={availableDocumentSets}
              availableTags={availableTags}
            />
          )}
        </div>
      </div>
      <div className="absolute bottom-2 mobile:right-4 desktop:right-4">
        <button
          className="cursor-pointer"
          onClick={() => {
            if (message) {
              onSubmit();
            }
          }}
        >
          <SendIcon
            size={22}
            className={`text-neutral-50 dark:text-neutral-900 p-1 my-auto rounded-full ${
              message
                ? "bg-neutral-900 dark:bg-neutral-50"
                : "bg-neutral-500 dark:bg-neutral-400"
            }`}
          />
        </button>
      </div>
    </div>
  );
}
