import React, { useContext, useEffect, useMemo, useRef, useState } from "react";
import { FiPlusCircle, FiPlus, FiX, FiFilter } from "react-icons/fi";
import { FiLoader } from "react-icons/fi";
import { ChatInputOption } from "./ChatInputOption";
import { Persona } from "@/app/admin/assistants/interfaces";
import LLMPopover from "./LLMPopover";
import { InputPrompt } from "@/app/chat/interfaces";

import { FilterManager, getDisplayNameForModel, LlmManager } from "@/lib/hooks";
import { useChatContext } from "@/components/context/ChatContext";
import { ChatFileType, FileDescriptor } from "../interfaces";
import {
  DocumentIcon2,
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
import { ChatState } from "../types";
import UnconfiguredProviderText from "@/components/chat/UnconfiguredProviderText";
import { useAssistants } from "@/components/context/AssistantsContext";
import { CalendarIcon, TagIcon, XIcon, FolderIcon } from "lucide-react";
import { FilterPopup } from "@/components/search/filtering/FilterPopup";
import { DocumentSet, Tag } from "@/lib/types";
import { SourceIcon } from "@/components/SourceIcon";
import { getFormattedDateRangeString } from "@/lib/dateUtils";
import { truncateString } from "@/lib/utils";
import { buildImgUrl } from "../files/images/utils";
import { useUser } from "@/components/user/UserProvider";
import { AgenticToggle } from "./AgenticToggle";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import { getProviderIcon } from "@/app/admin/configuration/llm/utils";
import { useDocumentsContext } from "../my-documents/DocumentsContext";
import { UploadIntent } from "../ChatPage";

const MAX_INPUT_HEIGHT = 200;
export const SourceChip2 = ({
  icon,
  title,
  onRemove,
  onClick,
  includeTooltip,
  includeAnimation,
  truncateTitle = true,
}: {
  icon: React.ReactNode;
  title: string;
  onRemove?: () => void;
  onClick?: () => void;
  truncateTitle?: boolean;
  includeTooltip?: boolean;
  includeAnimation?: boolean;
}) => {
  const [isNew, setIsNew] = useState(true);
  const [isTooltipOpen, setIsTooltipOpen] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setIsNew(false), 300);
    return () => clearTimeout(timer);
  }, []);

  return (
    <TooltipProvider>
      <Tooltip
        delayDuration={0}
        open={isTooltipOpen}
        onOpenChange={setIsTooltipOpen}
      >
        <TooltipTrigger
          onMouseEnter={() => setIsTooltipOpen(true)}
          onMouseLeave={() => setIsTooltipOpen(false)}
        >
          <div
            onClick={onClick ? onClick : undefined}
            className={`
            h-6
            px-2
            bg-background-dark
            rounded-2xl
            justify-center
            items-center
            inline-flex
            ${includeAnimation && isNew ? "animate-fade-in-scale" : ""}
            ${onClick ? "cursor-pointer" : ""}
          `}
          >
            <div className="w-[17px] h-4 p-[3px] flex-col justify-center items-center gap-2.5 inline-flex">
              <div className="h-2.5 relative">{icon}</div>
            </div>
            <div className="text-text-800 text-xs font-medium leading-normal">
              {truncateTitle ? truncateString(title, 50) : title}
            </div>
            {onRemove && (
              <XIcon
                size={12}
                className="text-text-800 ml-2 cursor-pointer"
                onClick={(e: React.MouseEvent<SVGSVGElement>) => {
                  e.stopPropagation();
                  onRemove();
                }}
              />
            )}
          </div>
        </TooltipTrigger>
        {includeTooltip && title.length > 50 && (
          <TooltipContent
            className="!pointer-events-none z-[2000000]"
            onMouseEnter={() => setIsTooltipOpen(false)}
          >
            <p>{title}</p>
          </TooltipContent>
        )}
      </Tooltip>
    </TooltipProvider>
  );
};

export const SourceChip = ({
  icon,
  title,
  onRemove,
  onClick,
  truncateTitle = true,
}: {
  icon?: React.ReactNode;
  title: string;
  onRemove?: () => void;
  onClick?: () => void;
  truncateTitle?: boolean;
}) => (
  <div
    onClick={onClick ? onClick : undefined}
    className={`
        flex-none
        flex
        items-center
        px-1
        bg-background-background
        text-xs
        text-text-darker
        border
        gap-x-1.5
        border-border
        rounded-md
        box-border
        gap-x-1
        h-6
        ${onClick ? "cursor-pointer" : ""}
      `}
  >
    {icon}
    {truncateTitle ? truncateString(title, 20) : title}
    {onRemove && (
      <XIcon
        size={12}
        className="text-text-900 ml-auto cursor-pointer"
        onClick={(e: React.MouseEvent<SVGSVGElement>) => {
          e.stopPropagation();
          onRemove();
        }}
      />
    )}
  </div>
);

interface ChatInputBarProps {
  toggleDocSelection: () => void;
  removeDocs: () => void;
  showConfigureAPIKey: () => void;
  selectedDocuments: OnyxDocument[];
  message: string;
  setMessage: (message: string) => void;
  stopGenerating: () => void;
  onSubmit: () => void;
  llmManager: LlmManager;
  chatState: ChatState;
  alternativeAssistant: Persona | null;
  // assistants
  selectedAssistant: Persona;
  setAlternativeAssistant: (alternativeAssistant: Persona | null) => void;
  toggleDocumentSidebar: () => void;
  setFiles: (files: FileDescriptor[]) => void;
  handleFileUpload: (files: File[], intent: UploadIntent) => void;
  textAreaRef: React.RefObject<HTMLTextAreaElement>;
  filterManager: FilterManager;
  availableSources: SourceMetadata[];
  availableDocumentSets: DocumentSet[];
  availableTags: Tag[];
  retrievalEnabled: boolean;
  proSearchEnabled: boolean;
  setProSearchEnabled: (proSearchEnabled: boolean) => void;
}

export function ChatInputBar({
  toggleDocSelection,
  retrievalEnabled,
  removeDocs,
  toggleDocumentSidebar,
  filterManager,
  showConfigureAPIKey,
  selectedDocuments,
  message,
  setMessage,
  stopGenerating,
  onSubmit,
  chatState,

  // assistants
  selectedAssistant,
  setAlternativeAssistant,

  setFiles,
  handleFileUpload,
  textAreaRef,
  alternativeAssistant,
  availableSources,
  availableDocumentSets,
  availableTags,
  llmManager,
  proSearchEnabled,
  setProSearchEnabled,
}: ChatInputBarProps) {
  const { user } = useUser();
  const {
    selectedFiles,
    selectedFolders,
    removeSelectedFile,
    removeSelectedFolder,
    currentMessageFiles,
    setCurrentMessageFiles,
  } = useDocumentsContext();

  // Create a Set of IDs from currentMessageFiles for efficient lookup
  // Assuming FileDescriptor.id corresponds conceptually to FileResponse.file_id or FileResponse.id
  const currentMessageFileIds = useMemo(
    () => new Set(currentMessageFiles.map((f) => String(f.id))), // Ensure IDs are strings for comparison
    [currentMessageFiles]
  );

  const settings = useContext(SettingsContext);
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
        handleFileUpload(pastedFiles, UploadIntent.ATTACH_TO_MESSAGE);
      }
    }
  };

  const { finalAssistants: assistantOptions } = useAssistants();

  const { llmProviders, inputPrompts } = useChatContext();

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

  const [showPrompts, setShowPrompts] = useState(false);

  const hidePrompts = () => {
    setTimeout(() => {
      setShowPrompts(false);
    }, 50);
    setTabbingIconIndex(0);
  };

  const updateInputPrompt = (prompt: InputPrompt) => {
    hidePrompts();
    setMessage(`${prompt.content}`);
  };

  const handlePromptInput = (text: string) => {
    if (!text.startsWith("/")) {
      hidePrompts();
    } else {
      const promptMatch = text.match(/(?:\s|^)\/(\w*)$/);
      if (promptMatch) {
        setShowPrompts(true);
      } else {
        hidePrompts();
      }
    }
  };

  const handleInputChange = (event: React.ChangeEvent<HTMLTextAreaElement>) => {
    const text = event.target.value;
    setMessage(text);
    handleAssistantInput(text);
    handlePromptInput(text);
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

  const filteredPrompts = inputPrompts.filter(
    (prompt) =>
      prompt.active &&
      prompt.prompt.toLowerCase().startsWith(
        message
          .slice(message.lastIndexOf("/") + 1)
          .split(/\s/)[0]
          .toLowerCase()
      )
  );

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (
      ((showSuggestions && assistantTagOptions.length > 0) || showPrompts) &&
      (e.key === "Tab" || e.key == "Enter")
    ) {
      e.preventDefault();

      if (
        (tabbingIconIndex == assistantTagOptions.length && showSuggestions) ||
        (tabbingIconIndex == filteredPrompts.length && showPrompts)
      ) {
        if (showPrompts) {
          window.open("/chat/input-prompts", "_self");
        } else {
          window.open("/assistants/new", "_self");
        }
      } else {
        if (showPrompts) {
          const selectedPrompt =
            filteredPrompts[tabbingIconIndex >= 0 ? tabbingIconIndex : 0];
          updateInputPrompt(selectedPrompt);
        } else {
          const option =
            assistantTagOptions[tabbingIconIndex >= 0 ? tabbingIconIndex : 0];
          updatedTaggedAssistant(option);
        }
      }
    }

    if (!showPrompts && !showSuggestions) {
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setTabbingIconIndex((tabbingIconIndex) =>
        Math.min(
          tabbingIconIndex + 1,
          showPrompts ? filteredPrompts.length : assistantTagOptions.length
        )
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
      <div className="flex  justify-center mx-auto">
        <div
          className="
            max-w-full
            w-[800px]
            relative
            desktop:px-4
            mx-auto
          "
        >
          {showSuggestions && assistantTagOptions.length > 0 && (
            <div
              ref={suggestionsRef}
              className="text-sm absolute w-[calc(100%-2rem)] top-0 transform -translate-y-full"
            >
              <div className="rounded-lg py-1 overflow-y-auto max-h-[200px] sm-1.5 bg-input-background border border-border dark:border-none shadow-lg px-1.5 mt-2 z-10">
                {assistantTagOptions.map((currentAssistant, index) => (
                  <button
                    key={index}
                    className={`px-2 ${
                      tabbingIconIndex == index &&
                      "bg-neutral-200 dark:bg-neutral-800"
                    } rounded items-center rounded-lg content-start flex gap-x-1 py-2 w-full hover:bg-neutral-200/90 dark:hover:bg-neutral-800/90 cursor-pointer`}
                    onClick={() => {
                      updatedTaggedAssistant(currentAssistant);
                    }}
                  >
                    <AssistantIcon size={16} assistant={currentAssistant} />
                    <p className="text-text-darker font-semibold">
                      {currentAssistant.name}
                    </p>
                    <p className="text-text-dark font-light line-clamp-1">
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
                    tabbingIconIndex == assistantTagOptions.length &&
                    "bg-neutral-200 dark:bg-neutral-800"
                  } rounded rounded-lg px-3 flex gap-x-1 py-2 w-full items-center hover:bg-neutral-200/90 dark:hover:bg-neutral-800/90 cursor-pointer`}
                  href="/assistants/new"
                >
                  <FiPlus size={17} />
                  <p>Create a new assistant</p>
                </a>
              </div>
            </div>
          )}

          {showPrompts && user?.preferences?.shortcut_enabled && (
            <div
              ref={suggestionsRef}
              className="text-sm absolute inset-x-0 top-0 w-full transform -translate-y-full"
            >
              <div className="rounded-lg overflow-y-auto max-h-[200px] py-1.5 bg-input-background dark:border-none border border-border shadow-lg mx-2 px-1.5 mt-2 rounded z-10">
                {filteredPrompts.map(
                  (currentPrompt: InputPrompt, index: number) => (
                    <button
                      key={index}
                      className={`px-2 ${
                        tabbingIconIndex == index &&
                        "bg-background-dark/75 dark:bg-neutral-800/75"
                      } rounded content-start flex gap-x-1 py-1.5 w-full hover:bg-background-dark/90 dark:hover:bg-neutral-800/90 cursor-pointer`}
                      onClick={() => {
                        updateInputPrompt(currentPrompt);
                      }}
                    >
                      <p className="font-bold">{currentPrompt.prompt}:</p>
                      <p className="text-left flex-grow mr-auto line-clamp-1">
                        {currentPrompt.content?.trim()}
                      </p>
                    </button>
                  )
                )}

                <a
                  key={filteredPrompts.length}
                  target="_self"
                  className={`${
                    tabbingIconIndex == filteredPrompts.length &&
                    "bg-background-dark/75 dark:bg-neutral-800/75"
                  } px-3 flex gap-x-1 py-2 w-full rounded-lg items-center hover:bg-background-dark/90 dark:hover:bg-neutral-800/90 cursor-pointer`}
                  href="/chat/input-prompts"
                >
                  <FiPlus size={17} />
                  <p>Create a new prompt</p>
                </a>
              </div>
            </div>
          )}

          <UnconfiguredProviderText showConfigureAPIKey={showConfigureAPIKey} />
          <div className="w-full h-[10px]"></div>
          <div
            className="
              opacity-100
              w-full
              h-fit
              flex
              flex-col
              border
              shadow
              bg-input-background
              border-input-border
              dark:border-none
              rounded-lg
              overflow-hidden
              text-text-chatbar
              [&:has(textarea:focus)]::ring-1
              [&:has(textarea:focus)]::ring-black
            "
          >
            {alternativeAssistant && (
              <div className="flex bg-background flex-wrap gap-x-2 px-2 pt-1.5 w-full">
                <div
                  ref={interactionsRef}
                  className="p-2 rounded-t-lg items-center flex w-full"
                >
                  <AssistantIcon assistant={alternativeAssistant} />
                  <p className="ml-3 text-strong my-auto">
                    {alternativeAssistant.name}
                  </p>
                  <div className="flex gap-x-1 ml-auto">
                    <Hoverable
                      icon={FiX}
                      onClick={() => setAlternativeAssistant(null)}
                    />
                  </div>
                </div>
              </div>
            )}

            <textarea
              onPaste={handlePaste}
              onKeyDownCapture={handleKeyDown}
              onChange={handleInputChange}
              ref={textAreaRef}
              id="onyx-chat-input-textarea"
              className={`
                m-0
                w-full
                shrink
                resize-none
                rounded-lg
                border-0
                bg-input-background
                font-normal
                text-base
                leading-6
                placeholder:text-input-text
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
                resize-none
                px-5
                py-4
                dark:text-[#D4D4D4]
              `}
              autoFocus
              style={{ scrollbarWidth: "thin" }}
              role="textarea"
              aria-multiline
              placeholder={`Message ${truncateString(
                selectedAssistant.name,
                70
              )} assistant...`}
              value={message}
              onKeyDown={(event) => {
                if (
                  event.key === "Enter" &&
                  !showPrompts &&
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

            {(selectedDocuments.length > 0 ||
              selectedFiles.length > 0 ||
              selectedFolders.length > 0 ||
              currentMessageFiles.length > 0 ||
              filterManager.timeRange ||
              filterManager.selectedDocumentSets.length > 0 ||
              filterManager.selectedTags.length > 0 ||
              filterManager.selectedSources.length > 0) && (
              <div className="flex bg-input-background gap-x-.5 px-2">
                <div className="flex gap-x-1 px-2 overflow-visible overflow-x-scroll items-end miniscroll">
                  {filterManager.selectedTags &&
                    filterManager.selectedTags.map((tag, index) => (
                      <SourceChip
                        key={index}
                        icon={<TagIcon size={12} />}
                        title={`#${tag.tag_key}_${tag.tag_value}`}
                        onRemove={() => {
                          filterManager.setSelectedTags(
                            filterManager.selectedTags.filter(
                              (t) => t.tag_key !== tag.tag_key
                            )
                          );
                        }}
                      />
                    ))}

                  {/* This is excluding image types because they get rendered differently via currentMessageFiles.map
                  Seems quite hacky ... all rendering should probably be done in one place? */}
                  {selectedFiles.map(
                    (file) =>
                      !currentMessageFileIds.has(
                        String(file.file_id || file.id)
                      ) && (
                        <SourceChip
                          key={file.id}
                          icon={<FileIcon size={16} />}
                          title={file.name}
                          onRemove={() => removeSelectedFile(file)}
                        />
                      )
                  )}
                  {selectedFolders.map((folder) => (
                    <SourceChip
                      key={folder.id}
                      icon={<FolderIcon size={16} />}
                      title={folder.name}
                      onRemove={() => removeSelectedFolder(folder)}
                    />
                  ))}
                  {filterManager.timeRange && (
                    <SourceChip
                      truncateTitle={false}
                      key="time-range"
                      icon={<CalendarIcon size={12} />}
                      title={`${getFormattedDateRangeString(
                        filterManager.timeRange.from,
                        filterManager.timeRange.to
                      )}`}
                      onRemove={() => {
                        filterManager.setTimeRange(null);
                      }}
                    />
                  )}
                  {filterManager.selectedDocumentSets.length > 0 &&
                    filterManager.selectedDocumentSets.map((docSet, index) => (
                      <SourceChip
                        key={`doc-set-${index}`}
                        icon={<DocumentIcon2 size={16} />}
                        title={docSet}
                        onRemove={() => {
                          filterManager.setSelectedDocumentSets(
                            filterManager.selectedDocumentSets.filter(
                              (ds) => ds !== docSet
                            )
                          );
                        }}
                      />
                    ))}
                  {filterManager.selectedSources.length > 0 &&
                    filterManager.selectedSources.map((source, index) => (
                      <SourceChip
                        key={`source-${index}`}
                        icon={
                          <SourceIcon
                            sourceType={source.internalName}
                            iconSize={16}
                          />
                        }
                        title={source.displayName}
                        onRemove={() => {
                          filterManager.setSelectedSources(
                            filterManager.selectedSources.filter(
                              (s) => s.internalName !== source.internalName
                            )
                          );
                        }}
                      />
                    ))}
                  {selectedDocuments.length > 0 && (
                    <SourceChip
                      key="selected-documents"
                      onClick={() => {
                        toggleDocumentSidebar();
                      }}
                      icon={<FileIcon size={16} />}
                      title={`${selectedDocuments.length} selected`}
                      onRemove={removeDocs}
                    />
                  )}
                  {currentMessageFiles.map((file, index) =>
                    file.type === ChatFileType.IMAGE ? (
                      <SourceChip
                        key={`file-${index}`}
                        icon={
                          file.isUploading ? (
                            <FiLoader className="animate-spin" />
                          ) : (
                            <img
                              className="h-full py-.5 object-cover rounded-lg bg-background cursor-pointer"
                              src={buildImgUrl(file.id)}
                              alt={file.name || "Uploaded image"}
                            />
                          )
                        }
                        title={file.name || "File" + file.id}
                        onRemove={() => {
                          setCurrentMessageFiles(
                            currentMessageFiles.filter(
                              (fileInFilter) => fileInFilter.id !== file.id
                            )
                          );
                        }}
                      />
                    ) : (
                      <SourceChip
                        key={`file-${index}`}
                        icon={<FileIcon className="text-red-500" size={16} />}
                        title={file.name || "File"}
                        onRemove={() => {
                          setCurrentMessageFiles(
                            currentMessageFiles.filter(
                              (fileInFilter) => fileInFilter.id !== file.id
                            )
                          );
                        }}
                      />
                    )
                  )}
                </div>
              </div>
            )}

            <div className="flex pr-4 pb-2 justify-between bg-input-background items-center w-full ">
              <div className="space-x-1 flex  px-4 ">
                <ChatInputOption
                  flexPriority="stiff"
                  name="File"
                  Icon={FiPlusCircle}
                  onClick={() => {
                    toggleDocSelection();
                  }}
                  tooltipContent={"Upload files and attach user files"}
                />

                <LLMPopover
                  llmProviders={llmProviders}
                  llmManager={llmManager}
                  requiresImageGeneration={false}
                  currentAssistant={selectedAssistant}
                  trigger={
                    <button
                      className="dark:text-white text-black focus:outline-none"
                      data-testid="llm-popover-trigger"
                    >
                      <ChatInputOption
                        minimize
                        toggle
                        flexPriority="stiff"
                        name={getDisplayNameForModel(
                          llmManager?.currentLlm.modelName || "Models"
                        )}
                        Icon={getProviderIcon(
                          llmManager?.currentLlm.provider || "anthropic",
                          llmManager?.currentLlm.modelName ||
                            "claude-3-5-sonnet-20240620"
                        )}
                        tooltipContent="Switch models"
                      />
                    </button>
                  }
                />

                {retrievalEnabled && (
                  <FilterPopup
                    availableSources={availableSources}
                    availableDocumentSets={
                      selectedAssistant.document_sets &&
                      selectedAssistant.document_sets.length > 0
                        ? selectedAssistant.document_sets
                        : availableDocumentSets
                    }
                    availableTags={availableTags}
                    filterManager={filterManager}
                    trigger={
                      <ChatInputOption
                        flexPriority="stiff"
                        name="Filters"
                        Icon={FiFilter}
                        toggle
                        tooltipContent="Filter your search"
                      />
                    }
                  />
                )}
              </div>
              <div className="flex items-center my-auto">
                {retrievalEnabled && settings?.settings.pro_search_enabled && (
                  <AgenticToggle
                    proSearchEnabled={proSearchEnabled}
                    setProSearchEnabled={setProSearchEnabled}
                  />
                )}
                <button
                  id="onyx-chat-input-send-button"
                  className={`cursor-pointer ${
                    chatState == "streaming" ||
                    chatState == "toolBuilding" ||
                    chatState == "loading"
                      ? chatState != "streaming"
                        ? "bg-neutral-500 dark:bg-neutral-400 "
                        : "bg-neutral-900 dark:bg-neutral-50"
                      : "bg-red-200"
                  } h-[22px] w-[22px] rounded-full`}
                  onClick={() => {
                    if (chatState == "streaming") {
                      stopGenerating();
                    } else if (message) {
                      onSubmit();
                    }
                  }}
                >
                  {chatState == "streaming" ||
                  chatState == "toolBuilding" ||
                  chatState == "loading" ? (
                    <StopGeneratingIcon
                      size={8}
                      className="text-neutral-50 dark:text-neutral-900 m-auto text-white flex-none"
                    />
                  ) : (
                    <SendIcon
                      size={22}
                      className={`text-neutral-50 dark:text-neutral-900 p-1 my-auto rounded-full ${
                        chatState == "input" && message
                          ? "bg-neutral-900 dark:bg-neutral-50"
                          : "bg-neutral-500 dark:bg-neutral-400"
                      }`}
                    />
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
