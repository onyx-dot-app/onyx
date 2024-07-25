import React, { useEffect, useRef, useState } from "react";
import { FiPlusCircle, FiPlus, FiInfo, FiX } from "react-icons/fi";
import { ChatInputOption } from "./ChatInputOption";
import { Persona } from "@/app/admin/assistants/interfaces";
import { FilterManager, LlmOverrideManager } from "@/lib/hooks";
import { SelectedFilterDisplay } from "./SelectedFilterDisplay";
import { useChatContext } from "@/components/context/ChatContext";
import { getFinalLLM } from "@/lib/llm/utils";
import { ChatFileType, FileDescriptor } from "../interfaces";
import {
  InputBarPreview,
  InputBarPreviewImageProvider,
} from "../files/InputBarPreview";
import {
  AssistantsIconSkeleton,
  CpuIconSkeleton,
  FileIcon,
  SendIcon,
} from "@/components/icons/icons";
import { IconType } from "react-icons";
import Popup from "../../../components/popup/Popup";
import { LlmTab } from "../modal/configuration/LlmTab";
import { AssistantsTab } from "../modal/configuration/AssistantsTab";
import { DanswerDocument } from "@/lib/search/interfaces";
import { AssistantIcon } from "@/components/assistants/AssistantIcon";
import { Tooltip } from "@/components/tooltip/Tooltip";
import { Hoverable } from "@/components/Hoverable";
const MAX_INPUT_HEIGHT = 200;

export function ChatInputBar({
  showDocs,
  selectedDocuments,
  message,
  setMessage,
  onSubmit,
  isStreaming,
  setIsCancelled,
  filterManager,
  llmOverrideManager,

  // assistants
  selectedAssistant,
  assistantOptions,
  setSelectedAssistant,
  setAlternativeAssistant,

  files,
  setFiles,
  handleFileUpload,
  textAreaRef,
  alternativeAssistant,
  chatSessionId,
}: {
  showDocs: () => void;
  selectedDocuments: DanswerDocument[];
  assistantOptions: Persona[];
  setAlternativeAssistant: (alternativeAssistant: Persona | null) => void;
  setSelectedAssistant: (assistant: Persona) => void;
  message: string;
  setMessage: (message: string) => void;
  onSubmit: () => void;
  isStreaming: boolean;
  setIsCancelled: (value: boolean) => void;
  filterManager: FilterManager;
  llmOverrideManager: LlmOverrideManager;
  selectedAssistant: Persona;
  alternativeAssistant: Persona | null;
  files: FileDescriptor[];
  setFiles: (files: FileDescriptor[]) => void;
  handleFileUpload: (files: File[]) => void;
  textAreaRef: React.RefObject<HTMLTextAreaElement>;
  chatSessionId?: number;
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

  const handlePaste = (event: React.ClipboardEvent) => {
    const items = event.clipboardData?.items;
    if (items) {
      const pastedFiles = [];
      for (let i = 0; i < items.length; i++) {
        if (items[i].kind === "file") {
          const file = items[i].getAsFile();
          if (file) pastedFiles.push(file);
        }
      }
      if (pastedFiles.length > 0) {
        event.preventDefault();
        handleFileUpload(pastedFiles);
      }
    }
  };

  const { llmProviders } = useChatContext();
  const [_, llmName] = getFinalLLM(llmProviders, selectedAssistant, null);

  const suggestionsRef = useRef<HTMLDivElement | null>(null);
  const [showSuggestions, setShowSuggestions] = useState(false);

  const interactionsRef = useRef<HTMLDivElement | null>(null);
  // Click out of assistant suggestions
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        suggestionsRef.current &&
        !suggestionsRef.current.contains(event.target as Node) &&
        (!interactionsRef.current ||
          !interactionsRef.current.contains(event.target as Node))
      ) {
        hideSuggestions();
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, []);

  const hideSuggestions = () => {
    setShowSuggestions(false);
    setAssistantIconIndex(0);
  };

  // Update selected persona
  const updatedTaggedAssistant = (assistant: Persona) => {
    setAlternativeAssistant(
      assistant.id == selectedAssistant.id ? null : assistant
    );
    hideSuggestions();
    setMessage("");
  };

  // Complete user input handling
  const handleInputChange = (event: React.ChangeEvent<HTMLTextAreaElement>) => {
    const text = event.target.value;
    setMessage(text);

    if (!text.startsWith("@")) {
      hideSuggestions();
      return;
    }

    const match = text.match(/(?:\s|^)@(\w*)$/);
    if (match) {
      setShowSuggestions(true);
    } else {
      hideSuggestions();
    }
  };

  const assistantTagOptions = assistantOptions.filter((assistant) =>
    assistant.name.toLowerCase().startsWith(
      message
        .slice(message.lastIndexOf("@") + 1)
        .split(/\s/)[0]
        .toLowerCase()
    )
  );

  const [assistantIconIndex, setAssistantIconIndex] = useState(0);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (
      showSuggestions &&
      assistantTagOptions.length > 0 &&
      (e.key === "Tab" || e.key == "Enter")
    ) {
      e.preventDefault();
      if (assistantIconIndex == assistantTagOptions.length) {
        window.open("/assistants/new", "_blank");
        hideSuggestions();
        setMessage("");
      } else {
        const option =
          assistantTagOptions[assistantIconIndex >= 0 ? assistantIconIndex : 0];
        updatedTaggedAssistant(option);
      }
    }
    if (!showSuggestions) {
      return;
    }

    if (e.key === "ArrowDown") {
      e.preventDefault();
      setAssistantIconIndex((assistantIconIndex) =>
        Math.min(assistantIconIndex + 1, assistantTagOptions.length)
      );
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setAssistantIconIndex((assistantIconIndex) =>
        Math.max(assistantIconIndex - 1, 0)
      );
    }
  };

  return (
    <div>
      <div className="flex justify-center pb-2 max-w-screen-lg mx-auto mb-2">
        <div
          className="
            w-[90%]
            shrink
            bg-background
            relative
            px-4
            max-w-searchbar-max
            mx-auto
          "
        >
          {showSuggestions && assistantTagOptions.length > 0 && (
            <div
              ref={suggestionsRef}
              className="text-sm absolute inset-x-0 top-0 w-full transform -translate-y-full"
            >
              <div className="rounded-lg py-1.5 bg-background border border-border-medium shadow-lg mx-2 px-1.5 mt-2 rounded z-10">
                {assistantTagOptions.map((currentAssistant, index) => (
                  <button
                    key={index}
                    className={`px-2 ${
                      assistantIconIndex == index && "bg-hover-lightish"
                    } rounded  rounded-lg content-start flex gap-x-1 py-2 w-full  hover:bg-hover-lightish cursor-pointer`}
                    onClick={() => {
                      updatedTaggedAssistant(currentAssistant);
                    }}
                  >
                    <p className="font-bold">{currentAssistant.name}</p>
                    <p className="line-clamp-1">
                      {currentAssistant.id == selectedAssistant.id &&
                        "(default) "}
                      {currentAssistant.description}
                    </p>
                  </button>
                ))}
                <a
                  key={assistantTagOptions.length}
                  target="_blank"
                  className={`${
                    assistantIconIndex == assistantTagOptions.length &&
                    "bg-hover"
                  } rounded rounded-lg px-3 flex gap-x-1 py-2 w-full  items-center  hover:bg-hover-lightish cursor-pointer"`}
                  href="/assistants/new"
                >
                  <FiPlus size={17} />
                  <p>Create a new assistant</p>
                </a>
              </div>
            </div>
          )}
          <div>
            <SelectedFilterDisplay filterManager={filterManager} />
          </div>
          <div
            className="
              opacity-100
              w-full
              h-fit
              bg-bl
              flex
              flex-col
              border
              border-[#E5E7EB]
              rounded-lg
              bg-background-100
              [&:has(textarea:focus)]::ring-1
              [&:has(textarea:focus)]::ring-black
            "
          >
            {alternativeAssistant && (
              <div className="flex flex-wrap gap-y-1 gap-x-2 px-2 pt-1.5 w-full">
                <div
                  ref={interactionsRef}
                  className="bg-background-200 p-2 rounded-t-lg items-center flex w-full"
                >
                  <AssistantIcon assistant={alternativeAssistant} border />
                  <p className="ml-3 text-strong my-auto">
                    {alternativeAssistant.name}
                  </p>
                  <div className="flex gap-x-1 ml-auto">
                    <Tooltip
                      content={
                        <p className="max-w-xs flex flex-wrap">
                          {alternativeAssistant.description}
                        </p>
                      }
                    >
                      <button>
                        <Hoverable icon={FiInfo} />
                      </button>
                    </Tooltip>

                    <Hoverable
                      icon={FiX}
                      onClick={() => setAlternativeAssistant(null)}
                    />
                  </div>
                </div>
              </div>
            )}
            {(selectedDocuments.length > 0 || files.length > 0) && (
              <div className="flex gap-x-2 px-2 pt-2">
                <div className="flex gap-x-1 px-2 overflow-y-auto overflow-x-scroll items-end miniscroll">
                  {selectedDocuments.length > 0 && (
                    <button
                      onClick={showDocs}
                      className="flex-none flex cursor-pointer hover:bg-background-200 transition-colors duration-300 h-10 p-1 items-center gap-x-1 rounded-lg bg-background-150 max-w-[100px]"
                    >
                      <FileIcon size={24} />
                      <p className="text-xs">
                        {selectedDocuments.length} selected
                      </p>
                    </button>
                  )}
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
              onKeyDownCapture={handleKeyDown}
              onChange={handleInputChange}
              ref={textAreaRef}
              className={`
                m-0
                w-full
                shrink
                resize-none
                rounded-lg
                border-0
                bg-background-100
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
                pl-4
                pr-12
                py-4
                h-14
              `}
              autoFocus
              style={{ scrollbarWidth: "thin" }}
              role="textarea"
              aria-multiline
              placeholder="Send a message or @ to tag an assistant..."
              value={message}
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

            <div className="flex items-center space-x-3 mr-12 px-4 pb-2 ">
              <Popup
                removePadding
                content={(close) => (
                  <AssistantsTab
                    availableAssistants={assistantOptions}
                    llmProviders={llmProviders}
                    selectedAssistant={selectedAssistant}
                    onSelect={(assistant) => {
                      setSelectedAssistant(assistant);
                      close();
                    }}
                  />
                )}
                position="top"
              >
                <ChatInputOption
                  flexPriority="shrink"
                  name={
                    selectedAssistant ? selectedAssistant.name : "Assistants"
                  }
                  Icon={AssistantsIconSkeleton as IconType}
                />
              </Popup>

              <Popup
                content={(close, ref) => (
                  <LlmTab
                    close={close}
                    ref={ref}
                    llmOverrideManager={llmOverrideManager}
                    chatSessionId={chatSessionId}
                    currentAssistant={selectedAssistant}
                  />
                )}
                position="top"
              >
                <ChatInputOption
                  flexPriority="second"
                  name={
                    llmOverrideManager.llmOverride.modelName ||
                    (selectedAssistant
                      ? selectedAssistant.llm_model_version_override || llmName
                      : llmName)
                  }
                  Icon={CpuIconSkeleton}
                />
              </Popup>

              <ChatInputOption
                flexPriority="stiff"
                name="File"
                Icon={FiPlusCircle}
                onClick={() => {
                  const input = document.createElement("input");
                  input.type = "file";
                  input.multiple = true; // Allow multiple files
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
                <SendIcon
                  size={28}
                  className={`text-emphasis text-white p-1 rounded-full ${
                    message ? "bg-background-800" : "bg-[#D7D7D7]"
                  }`}
                />
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
