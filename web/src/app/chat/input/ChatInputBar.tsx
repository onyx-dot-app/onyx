import React, { useContext, useEffect, useRef, useState } from "react";
import { FiPlusCircle, FiPlus, FiInfo, FiX, FiSearch } from "react-icons/fi";
import { ChatInputOption } from "./ChatInputOption";
import { Persona } from "@/app/admin/assistants/interfaces";

import { FilterManager } from "@/lib/hooks";
import { useChatContext } from "@/components/context/ChatContext";
import { getFinalLLM } from "@/lib/llm/utils";
import { ChatFileType, FileDescriptor } from "../interfaces";
import {
  InputBarPreview,
  InputBarPreviewImageProvider,
} from "../files/InputBarPreview";
import {
  AssistantsIconSkeleton,
  FileIcon,
  SendIcon,
  StopGeneratingIcon,
} from "@/components/icons/icons";
import { OnyxDocument, SourceMetadata } from "@/lib/search/interfaces";
import { AssistantIcon } from "@/components/assistants/AssistantIcon";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Hoverable } from "@/components/Hoverable";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import { ChatState } from "../types";
import UnconfiguredProviderText from "@/components/chat_search/UnconfiguredProviderText";
import { useAssistants } from "@/components/context/AssistantsContext";
import { XIcon } from "lucide-react";
import FiltersDisplay from "./FilterDisplay";

const MAX_INPUT_HEIGHT = 200;

interface ChatInputBarProps {
  removeDocs: () => void;
  openModelSettings: () => void;
  showDocs: () => void;
  showConfigureAPIKey: () => void;
  selectedDocuments: OnyxDocument[];
  message: string;
  setMessage: (message: string) => void;
  stopGenerating: () => void;
  onSubmit: () => void;
  filterManager: FilterManager;
  chatState: ChatState;
  alternativeAssistant: Persona | null;
  // assistants
  selectedAssistant: Persona;
  setAlternativeAssistant: (alternativeAssistant: Persona | null) => void;

  files: FileDescriptor[];
  setFiles: (files: FileDescriptor[]) => void;
  handleFileUpload: (files: File[]) => void;
  textAreaRef: React.RefObject<HTMLTextAreaElement>;
  toggleFilters?: () => void;
}

export function ChatInputBar({
  removeDocs,
  openModelSettings,
  showDocs,
  showConfigureAPIKey,
  selectedDocuments,
  message,
  setMessage,
  stopGenerating,
  onSubmit,
  filterManager,
  chatState,

  // assistants
  selectedAssistant,
  setAlternativeAssistant,

  files,
  setFiles,
  handleFileUpload,
  textAreaRef,
  alternativeAssistant,
  toggleFilters,
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

  const settings = useContext(SettingsContext);
  const { finalAssistants: assistantOptions } = useAssistants();

  const { llmProviders } = useChatContext();
  const [_, llmName] = getFinalLLM(llmProviders, selectedAssistant, null);

  const suggestionsRef = useRef<HTMLDivElement | null>(null);
  const [showSuggestions, setShowSuggestions] = useState(false);

  const interactionsRef = useRef<HTMLDivElement | null>(null);

  const hideSuggestions = () => {
    setShowSuggestions(false);
    setTabbingIconIndex(0);
  };

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

  const updatedTaggedAssistant = (assistant: Persona) => {
    setAlternativeAssistant(
      assistant.id == selectedAssistant.id ? null : assistant
    );
    hideSuggestions();
    setMessage("");
  };

  const handleAssistantInput = (text: string) => {
    if (!text.startsWith("@")) {
      hideSuggestions();
    } else {
      const match = text.match(/(?:\s|^)@(\w*)$/);
      if (match) {
        setShowSuggestions(true);
      } else {
        hideSuggestions();
      }
    }
  };

  const handleInputChange = (event: React.ChangeEvent<HTMLTextAreaElement>) => {
    const text = event.target.value;
    setMessage(text);
    handleAssistantInput(text);
  };

  const assistantTagOptions = assistantOptions.filter((assistant) =>
    assistant.name.toLowerCase().startsWith(
      message
        .slice(message.lastIndexOf("@") + 1)
        .split(/\s/)[0]
        .toLowerCase()
    )
  );

  const [tabbingIconIndex, setTabbingIconIndex] = useState(0);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (
      showSuggestions &&
      assistantTagOptions.length > 0 &&
      (e.key === "Tab" || e.key == "Enter")
    ) {
      e.preventDefault();

      if (tabbingIconIndex == assistantTagOptions.length && showSuggestions) {
        window.open("/assistants/new", "_self");
      } else {
        const option =
          assistantTagOptions[tabbingIconIndex >= 0 ? tabbingIconIndex : 0];

        updatedTaggedAssistant(option);
      }
    }
    if (!showSuggestions) {
      return;
    }

    if (e.key === "ArrowDown") {
      e.preventDefault();

      setTabbingIconIndex((tabbingIconIndex) =>
        Math.min(tabbingIconIndex + 1, assistantTagOptions.length)
      );
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setTabbingIconIndex((tabbingIconIndex) =>
        Math.max(tabbingIconIndex - 1, 0)
      );
    }
  };

  return (
    <div id="onyx-chat-input">
      <div className="flex justify-center mx-auto">
        <div
          className="
            w-[800px]
            relative
            desktop:px-4
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
                      tabbingIconIndex == index && "bg-hover-lightish"
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
                  target="_self"
                  className={`${
                    tabbingIconIndex == assistantTagOptions.length && "bg-hover"
                  } rounded rounded-lg px-3 flex gap-x-1 py-2 w-full  items-center  hover:bg-hover-lightish cursor-pointer"`}
                  href="/assistants/new"
                >
                  <FiPlus size={17} />
                  <p>Create a new assistant</p>
                </a>
              </div>
            </div>
          )}

          <UnconfiguredProviderText showConfigureAPIKey={showConfigureAPIKey} />

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
              text-text-chatbar
              bg-background-chatbar
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
                  <AssistantIcon assistant={alternativeAssistant} />
                  <p className="ml-3 text-strong my-auto">
                    {alternativeAssistant.name}
                  </p>
                  <div className="flex gap-x-1 ml-auto">
                    <TooltipProvider>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <button>
                            <Hoverable icon={FiInfo} />
                          </button>
                        </TooltipTrigger>
                        <TooltipContent>
                          <p className="max-w-xs flex flex-wrap">
                            {alternativeAssistant.description}
                          </p>
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>

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
                <div className="flex gap-x-1 px-2 overflow-visible overflow-x-scroll items-end miniscroll">
                  {selectedDocuments.length > 0 && (
                    <button
                      onClick={showDocs}
                      className="flex-none relative overflow-visible flex items-center gap-x-2 h-10 px-3 rounded-lg bg-background-150 hover:bg-background-200 transition-colors duration-300 cursor-pointer max-w-[150px]"
                    >
                      <FileIcon size={20} />
                      <span className="text-sm whitespace-nowrap overflow-hidden text-ellipsis">
                        {selectedDocuments.length} selected
                      </span>
                      <XIcon
                        onClick={removeDocs}
                        size={16}
                        className="text-text-400 hover:text-text-600 ml-auto"
                      />
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
                bg-background-chatbar
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
              placeholder="Ask me anything.."
              value={message}
              onKeyDown={(event) => {
                if (
                  event.key === "Enter" &&
                  !showSuggestions &&
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
              {toggleFilters && (
                <ChatInputOption
                  flexPriority="stiff"
                  name="Filters"
                  Icon={FiSearch}
                  onClick={toggleFilters}
                />
              )}
              {(filterManager.selectedSources.length > 0 ||
                filterManager.selectedDocumentSets.length > 0 ||
                filterManager.selectedTags.length > 0 ||
                filterManager.timeRange) &&
                toggleFilters && (
                  <FiltersDisplay
                    filterManager={filterManager}
                    toggleFilters={toggleFilters}
                  />
                )}
            </div>

            <div className="absolute bottom-2.5 mobile:right-4 desktop:right-10">
              {chatState == "streaming" ||
              chatState == "toolBuilding" ||
              chatState == "loading" ? (
                <button
                  className={`cursor-pointer ${
                    chatState != "streaming"
                      ? "bg-background-400"
                      : "bg-background-800"
                  }  h-[28px] w-[28px] rounded-full`}
                  onClick={stopGenerating}
                  disabled={chatState != "streaming"}
                >
                  <StopGeneratingIcon
                    size={10}
                    className={`text-emphasis m-auto text-white flex-none
                      }`}
                  />
                </button>
              ) : (
                <button
                  className="cursor-pointer"
                  onClick={() => {
                    if (message) {
                      onSubmit();
                    }
                  }}
                  disabled={chatState != "input"}
                >
                  <SendIcon
                    size={28}
                    className={`text-emphasis text-white p-1 rounded-full  ${
                      chatState == "input" && message
                        ? "bg-submit-background"
                        : "bg-disabled-submit-background"
                    } `}
                  />
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
