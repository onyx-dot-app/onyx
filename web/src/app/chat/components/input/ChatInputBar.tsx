import React, {
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { FiPlus } from "react-icons/fi";
import { FiLoader } from "react-icons/fi";
import { ChatInputOption } from "./ChatInputOption";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import LLMPopover from "./LLMPopover";
import { InputPrompt } from "@/app/chat/interfaces";

import { FilterManager, LlmManager, useFederatedConnectors } from "@/lib/hooks";
import { useChatContext } from "@/components/context/ChatContext";
import {
  DocumentIcon2,
  FileIcon,
  SendIcon,
  StopGeneratingIcon,
} from "@/components/icons/icons";
import { OnyxDocument, MinimalOnyxDocument } from "@/lib/search/interfaces";
import { ChatState } from "@/app/chat/interfaces";
import { useAssistantsContext } from "@/components/context/AssistantsContext";
import { CalendarIcon, TagIcon, XIcon } from "lucide-react";
import { SourceIcon } from "@/components/SourceIcon";
import { getFormattedDateRangeString } from "@/lib/dateUtils";
import { truncateString } from "@/lib/utils";
import { useUser } from "@/components/user/UserProvider";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import { UnconfiguredLlmProviderText } from "@/components/chat/UnconfiguredLlmProviderText";
import { DeepResearchToggle } from "./DeepResearchToggle";
import { ActionToggle } from "./ActionManagement";
import { SelectedTool } from "./SelectedTool";
import { getProviderIcon } from "@/app/admin/configuration/llm/utils";
import FilePicker from "../files/FilePicker";
import { useProjectsContext } from "../../projects/ProjectsContext";
import { FileCard } from "../projects/ProjectContextPanel";
import {
  ProjectFile,
  UserFileStatus,
} from "@/app/chat/projects/projectsService";

const MAX_INPUT_HEIGHT = 200;

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
  removeDocs: () => void;
  showConfigureAPIKey: () => void;
  selectedDocuments: OnyxDocument[];
  message: string;
  setMessage: (message: string) => void;
  stopGenerating: () => void;
  onSubmit: () => void;
  llmManager: LlmManager;
  chatState: ChatState;
  currentSessionFileTokenCount: number;
  availableContextTokens: number;
  // assistants
  selectedAssistant: MinimalPersonaSnapshot;

  toggleDocumentSidebar: () => void;
  handleFileUpload: (files: File[]) => void;
  textAreaRef: React.RefObject<HTMLTextAreaElement>;
  filterManager: FilterManager;
  retrievalEnabled: boolean;
  deepResearchEnabled: boolean;
  setPresentingDocument?: (document: MinimalOnyxDocument) => void;
  toggleDeepResearch: () => void;
  placeholder?: string;
}

export const ChatInputBar = React.memo(function ChatInputBar({
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
  currentSessionFileTokenCount,
  availableContextTokens,
  // assistants
  selectedAssistant,

  handleFileUpload,
  textAreaRef,
  llmManager,
  deepResearchEnabled,
  toggleDeepResearch,
  placeholder,
  setPresentingDocument,
}: ChatInputBarProps) {
  const { user } = useUser();

  const { forcedToolIds, setForcedToolIds } = useAssistantsContext();
  const { currentMessageFiles, setCurrentMessageFiles, recentFiles } =
    useProjectsContext();

  const currentIndexingFiles = useMemo(() => {
    return currentMessageFiles.filter(
      (file) => file.status === UserFileStatus.PROCESSING
    );
  }, [currentMessageFiles]);

  // Convert ProjectFile to MinimalOnyxDocument format for viewing
  const handleFileClick = useCallback(
    (file: ProjectFile) => {
      if (!setPresentingDocument) return;

      const documentForViewer: MinimalOnyxDocument = {
        document_id: `project_file__${file.file_id}`,
        semantic_identifier: file.name,
      };

      setPresentingDocument(documentForViewer);
    },
    [setPresentingDocument]
  );

  const handleUploadChange = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = e.target.files;
      if (!files || files.length === 0) return;
      handleFileUpload(Array.from(files));
      e.target.value = "";
    },
    [handleFileUpload]
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

  const handleRemoveMessageFile = useCallback(
    (fileId: string) => {
      setCurrentMessageFiles((prev) => prev.filter((f) => f.id !== fileId));
    },
    [setCurrentMessageFiles]
  );

  const {
    llmProviders,
    inputPrompts,
    ccPairs,
    availableSources,
    documentSets,
  } = useChatContext();
  const { data: federatedConnectorsData } = useFederatedConnectors();
  const [showPrompts, setShowPrompts] = useState(false);

  // Memoize availableSources to prevent unnecessary re-renders
  const memoizedAvailableSources = useMemo(
    () => [
      ...ccPairs.map((ccPair) => ccPair.source),
      ...(federatedConnectorsData?.map((connector) => connector.source) || []),
    ],
    [ccPairs, federatedConnectorsData]
  );

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

  const handlePromptInput = useCallback(
    (text: string) => {
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
    },
    [hidePrompts]
  );

  const handleInputChange = useCallback(
    (event: React.ChangeEvent<HTMLTextAreaElement>) => {
      const text = event.target.value;
      setMessage(text);
      handlePromptInput(text);
    },
    [setMessage, handlePromptInput]
  );

  const startFilterSlash = useMemo(() => {
    if (message !== undefined) {
      const message_segments = message
        .slice(message.lastIndexOf("/") + 1)
        .split(/\s/);
      if (message_segments[0]) {
        return message_segments[0].toLowerCase();
      }
    }
    return "";
  }, [message]);

  const [tabbingIconIndex, setTabbingIconIndex] = useState(0);

  const filteredPrompts = useMemo(
    () =>
      inputPrompts.filter(
        (prompt) =>
          prompt.active &&
          prompt.prompt.toLowerCase().startsWith(startFilterSlash)
      ),
    [inputPrompts, startFilterSlash]
  );

  // Determine if we should hide processing state based on context limits
  const hideProcessingState = useMemo(() => {
    if (currentMessageFiles.length > 0 && currentIndexingFiles.length > 0) {
      const currentFilesTokenTotal = currentMessageFiles.reduce(
        (acc, file) => acc + (file.token_count || 0),
        0
      );
      const totalTokens =
        (currentSessionFileTokenCount || 0) + currentFilesTokenTotal;
      // Hide processing state when files are within context limits
      return totalTokens < availableContextTokens;
    }
    return false;
  }, [
    currentMessageFiles,
    currentSessionFileTokenCount,
    currentIndexingFiles,
    availableContextTokens,
  ]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (showPrompts && (e.key === "Tab" || e.key == "Enter")) {
      e.preventDefault();

      if (tabbingIconIndex == filteredPrompts.length && showPrompts) {
        if (showPrompts) {
          window.open("/chat/input-prompts", "_self");
        }
      } else {
        if (showPrompts) {
          const selectedPrompt =
            filteredPrompts[tabbingIconIndex >= 0 ? tabbingIconIndex : 0];
          if (selectedPrompt) {
            updateInputPrompt(selectedPrompt);
          }
        }
      }
    }

    if (!showPrompts) {
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setTabbingIconIndex((tabbingIconIndex) =>
        Math.min(tabbingIconIndex + 1, filteredPrompts.length)
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
            max-w-full
            w-[800px]
            relative
            desktop:px-4
            mx-auto
          "
        >
          {showPrompts && user?.preferences?.shortcut_enabled && (
            <div className="text-sm absolute inset-x-0 top-0 w-full transform -translate-y-full">
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

          <UnconfiguredLlmProviderText
            showConfigureAPIKey={showConfigureAPIKey}
          />
          <div className="w-full h-[10px]"></div>
          <div className="relative">
            <div
              className="
                opacity-100
                w-full
                h-fit
                flex
                flex-col
                border
                shadow-lg
                bg-input-background
                border-input-border
                dark:border-none
                rounded-xl
                overflow-hidden
                text-text-chatbar
                [&:has(textarea:focus)]::ring-1
                [&:has(textarea:focus)]::ring-black
              "
              style={{ position: "relative", zIndex: 10 }}
            >
              {currentMessageFiles.length > 0 && (
                <div className="px-4 pt-4">
                  <div className="flex flex-wrap gap-2">
                    {currentMessageFiles.map((file) => (
                      <FileCard
                        key={file.id}
                        file={file}
                        removeFile={handleRemoveMessageFile}
                        hideProcessingState={hideProcessingState}
                        onFileClick={handleFileClick}
                      />
                    ))}
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
                placeholder:text-text-400 dark:placeholder:text-text-500
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
                py-5
              `}
                autoFocus
                style={{ scrollbarWidth: "thin" }}
                role="textarea"
                aria-multiline
                placeholder={
                  placeholder ||
                  (selectedAssistant.id === 0
                    ? `How can ${settings?.enterpriseSettings?.application_name || "Onyx"} help you today`
                    : `How can ${selectedAssistant.name} help you today`)
                }
                value={message}
                onKeyDown={(event) => {
                  if (
                    event.key === "Enter" &&
                    !showPrompts &&
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
                currentMessageFiles.length > 0 ||
                filterManager.timeRange ||
                filterManager.selectedDocumentSets.length > 0 ||
                filterManager.selectedTags.length > 0) && (
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
                      filterManager.selectedDocumentSets.map(
                        (docSet, index) => (
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
                        )
                      )}
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
                  </div>
                </div>
              )}

              <div className="flex pr-4 pb-2 justify-between bg-input-background items-center w-full ">
                <div className="space-x-1 flex px-4 items-center">
                  <FilePicker
                    onFileClick={handleFileClick}
                    onPickRecent={(file: ProjectFile) => {
                      // Check if file with same ID already exists
                      if (
                        !currentMessageFiles.some(
                          (existingFile) =>
                            existingFile.file_id === file.file_id
                        )
                      ) {
                        setCurrentMessageFiles((prev) => [...prev, file]);
                      }
                    }}
                    recentFiles={recentFiles}
                    handleUploadChange={handleUploadChange}
                  />

                  {selectedAssistant.tools.length > 0 && (
                    <ActionToggle
                      selectedAssistant={selectedAssistant}
                      availableSources={memoizedAvailableSources}
                      filterManager={filterManager}
                    />
                  )}

                  {retrievalEnabled &&
                    settings?.settings.deep_research_enabled && (
                      <DeepResearchToggle
                        deepResearchEnabled={deepResearchEnabled}
                        toggleDeepResearch={toggleDeepResearch}
                      />
                    )}

                  {forcedToolIds.length > 0 && (
                    <div className="pl-1 flex items-center gap-2 text-blue-500">
                      {forcedToolIds.map((toolId) => {
                        const tool = selectedAssistant.tools.find(
                          (tool) => tool.id === toolId
                        );
                        if (!tool) {
                          return null;
                        }
                        return (
                          <SelectedTool
                            key={toolId}
                            tool={tool}
                            onClick={() => {
                              setForcedToolIds((prev) =>
                                prev.filter((id) => id !== toolId)
                              );
                            }}
                          />
                        );
                      })}
                    </div>
                  )}
                </div>

                <div className="flex items-center my-auto gap-x-2">
                  <LLMPopover
                    llmProviders={llmProviders}
                    llmManager={llmManager}
                    requiresImageGeneration={true}
                    currentAssistant={selectedAssistant}
                  />

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
    </div>
  );
});
