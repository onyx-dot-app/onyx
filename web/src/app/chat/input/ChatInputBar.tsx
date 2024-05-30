import React, { useEffect, useRef } from "react";
import { FiSend, FiFilter, FiPlusCircle, FiCpu } from "react-icons/fi";
import ChatInputOption from "./ChatInputOption";
import { FaBrain } from "react-icons/fa";
import { Persona } from "@/app/admin/assistants/interfaces";
import { FilterManager, LlmOverride, LlmOverrideManager } from "@/lib/hooks";
import { SelectedFilterDisplay } from "./SelectedFilterDisplay";
import { useChatContext } from "@/components/context/ChatContext";
import { getFinalLLM } from "@/lib/llm/utils";
import { FileDescriptor } from "../interfaces";
import { InputBarPreview } from "../files/InputBarPreview";

const MAX_INPUT_HEIGHT = 200;

export function ChatInputBar({
  message,
  setMessage,
  onSubmit,
  isStreaming,
  setIsCancelled,
  retrievalDisabled,
  filterManager,
  llmOverrideManager,
  selectedAssistant,
  files,
  setFiles,
  handleFileUpload,
  setConfigModalActiveTab,
  textAreaRef,
}: {
  message: string;
  setMessage: (message: string) => void;
  onSubmit: () => void;
  isStreaming: boolean;
  setIsCancelled: (value: boolean) => void;
  retrievalDisabled: boolean;
  filterManager: FilterManager;
  llmOverrideManager: LlmOverrideManager;
  selectedAssistant: Persona;
  files: FileDescriptor[];
  setFiles: (files: FileDescriptor[]) => void;
  handleFileUpload: (files: File[]) => void;
  setConfigModalActiveTab: (tab: string) => void;
  textAreaRef: React.RefObject<HTMLTextAreaElement>;
}) {
  // handle re-sizing of the text area
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

  const { llmProviders } = useChatContext();
  const [_, llmName] = getFinalLLM(llmProviders, selectedAssistant);

  return (
    <div>
      <div className="flex justify-center pb-2 max-w-screen-lg mx-auto mb-2">
        <div
          className="
            w-full
            shrink
            relative
            px-4
            w-searchbar-xs
            2xl:w-searchbar-sm
            3xl:w-searchbar
            mx-auto
          "
        >
          <div>
            <SelectedFilterDisplay filterManager={filterManager} />
          </div>
          <div
            className="
              opacity-100
              w-full
              h-fit
              flex
              flex-col
              border
              border-border
              rounded-lg
              bg-background
              [&:has(textarea:focus)]::ring-1
              [&:has(textarea:focus)]::ring-black
            "
          >
            {files.length > 0 && (
              <div className="flex flex-wrap gap-y-1 gap-x-2 px-2 pt-2">
                {files.map((file) => (
                  <div key={file.id}>
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
                  </div>
                ))}
              </div>
            )}
            <textarea
              ref={textAreaRef}
              className={`
                m-0
                w-full
                shrink
                resize-none
                border-0
                bg-transparent
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
                placeholder-gray-400
                overflow-hidden
                resize-none
                pl-4
                pr-12
                py-4
                h-14
              `}
              autoFocus
              style={{ scrollbarWidth: "thin" }}
              role="textarea"
              aria-multiline
              placeholder="Send a message..."
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              onKeyDown={(event) => {
                if (
                  event.key === "Enter" &&
                  !event.shiftKey &&
                  message &&
                  !isStreaming
                ) {
                  onSubmit();
                  event.preventDefault();
                }
              }}
              suppressContentEditableWarning={true}
            />
            <div className="flex items-center space-x-3 px-4 pb-2">
              <ChatInputOption
                name={selectedAssistant ? selectedAssistant.name : "Assistants"}
                icon={FaBrain}
                onClick={() => setConfigModalActiveTab("assistants")}
              />
              <ChatInputOption
                name={
                  llmOverrideManager.llmOverride.modelName ||
                  (selectedAssistant
                    ? selectedAssistant.llm_model_version_override || llmName
                    : llmName)
                }
                icon={FiCpu}
                onClick={() => setConfigModalActiveTab("llms")}
              />
              {!retrievalDisabled && (
                <ChatInputOption
                  name="Filters"
                  icon={FiFilter}
                  onClick={() => setConfigModalActiveTab("filters")}
                />
              )}
              <ChatInputOption
                name="File"
                icon={FiPlusCircle}
                onClick={() => {
                  const input = document.createElement("input");
                  input.type = "file";
                  input.onchange = (event: any) => {
                    const files = Array.from(
                      event?.target?.files || []
                    ) as File[];
                    if (files.length > 0) {
                      handleFileUpload(files);
                    }
                  };
                  input.click();
                }}
              />
            </div>
            <div className="absolute bottom-2.5 right-10">
              <div
                className="cursor-pointer"
                onClick={() => {
                  if (!isStreaming) {
                    if (message) {
                      onSubmit();
                    }
                  } else {
                    setIsCancelled(true);
                  }
                }}
              >
                <FiSend
                  size={18}
                  className={`text-emphasis w-9 h-9 p-2 rounded-lg ${
                    message ? "bg-blue-200" : ""
                  }`}
                />
              </div>
            </div>
          </div>
        </div>
      </div>
      {/* <div className="text-center text-sm text-subtle mt-2">
        Press "/" for shortcuts and useful prompts
      </div> */}
    </div>
  );
}
