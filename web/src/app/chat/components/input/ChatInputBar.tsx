import React, {
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { FiPlus } from "react-icons/fi";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import LLMPopover from "@/refresh-components/LLMPopover";
import { InputPrompt } from "@/app/chat/interfaces";
import { FilterManager, LlmManager, useFederatedConnectors } from "@/lib/hooks";
import { useChatContext } from "@/refresh-components/contexts/ChatContext";
import { DocumentIcon2, FileIcon } from "@/components/icons/icons";
import { OnyxDocument, MinimalOnyxDocument } from "@/lib/search/interfaces";
import { ChatState } from "@/app/chat/interfaces";
import { useAgentsContext } from "@/refresh-components/contexts/AgentsContext";
import { CalendarIcon, XIcon } from "lucide-react";
import { getFormattedDateRangeString } from "@/lib/dateUtils";
import { truncateString, cn } from "@/lib/utils";
import { useUser } from "@/components/user/UserProvider";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import { UnconfiguredLlmProviderText } from "@/components/chat/UnconfiguredLlmProviderText";
import { useProjectsContext } from "@/app/chat/projects/ProjectsContext";
import { FileCard } from "@/app/chat/components/projects/ProjectContextPanel";
import {
  ProjectFile,
  UserFileStatus,
} from "@/app/chat/projects/projectsService";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgHourglass from "@/icons/hourglass";
import SvgArrowUp from "@/icons/arrow-up";
import SvgStop from "@/icons/stop";
import FilePicker from "@/app/chat/components/files/FilePicker";
import { ActionToggle } from "@/app/chat/components/input/ActionManagement";
import SelectButton from "@/refresh-components/buttons/SelectButton";
import SvgPlusCircle from "@/icons/plus-circle";
import {
  getIconForAction,
  hasSearchToolsAvailable,
} from "../../services/actionUtils";

const MAX_INPUT_HEIGHT = 200;

export interface SourceChipProps {
  icon?: React.ReactNode;
  title: string;
  onRemove?: () => void;
  onClick?: () => void;
  truncateTitle?: boolean;
}

export function SourceChip({
  icon,
  title,
  onRemove,
  onClick,
  truncateTitle = true,
}: SourceChipProps) {
  return (
    <div
      onClick={onClick ? onClick : undefined}
      className={cn(
        "flex-none flex items-center px-1 bg-background-neutral-01 text-xs text-text-04 border gap-x-1.5 border-border-01 rounded-08 box-border gap-x-1 h-6",
        onClick && "cursor-pointer"
      )}
    >
      {icon}
      {truncateTitle ? truncateString(title, 20) : title}
      {onRemove && (
        <XIcon
          size={12}
          className="text-text-01 ml-auto cursor-pointer"
          onClick={(e: React.MouseEvent<SVGSVGElement>) => {
            e.stopPropagation();
            onRemove();
          }}
        />
      )}
    </div>
  );
}

export interface ChatInputBarProps {
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
}

function ChatInputBarInner({
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
  setPresentingDocument,
}: ChatInputBarProps) {
  const { user } = useUser();

  const { forcedToolIds, setForcedToolIds } = useAgentsContext();
  const {
    currentMessageFiles,
    setCurrentMessageFiles,
    recentFiles,
    allRecentFiles,
  } = useProjectsContext();

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

  // Check if the assistant has search tools available (internal search or web search)
  const showDeepResearch = useMemo(() => {
    return hasSearchToolsAvailable(selectedAssistant.tools);
  }, [selectedAssistant.tools]);

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
    <div id="onyx-chat-input" className="max-w-full w-[50rem]">
      {showPrompts && user?.preferences?.shortcut_enabled && (
        <div className="text-sm absolute inset-x-0 top-0 w-full transform -translate-y-full">
          <div className="rounded-lg overflow-y-auto max-h-[200px] py-1.5 bg-background-neutral-01 border border-border-01 shadow-lg mx-2 px-1.5 mt-2 rounded z-10">
            {filteredPrompts.map(
              (currentPrompt: InputPrompt, index: number) => (
                <button
                  key={index}
                  className={cn(
                    "px-2 rounded content-start flex gap-x-1 py-1.5 w-full cursor-pointer",
                    tabbingIconIndex == index && "bg-background-neutral-02",
                    "hover:bg-background-neutral-02"
                  )}
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
              className={cn(
                "px-3 flex gap-x-1 py-2 w-full rounded-lg items-center cursor-pointer",
                tabbingIconIndex == filteredPrompts.length &&
                  "bg-background-neutral-02",
                "hover:bg-background-neutral-02"
              )}
              href="/chat/input-prompts"
            >
              <FiPlus size={17} />
              <p>Create a new prompt</p>
            </a>
          </div>
        </div>
      )}

      <UnconfiguredLlmProviderText showConfigureAPIKey={showConfigureAPIKey} />

      <div className="w-full h-full flex flex-col shadow-01 bg-background-neutral-00 rounded-16">
        {currentMessageFiles.length > 0 && (
          <div className="p-spacing-inline rounded-t-16 flex flex-wrap gap-spacing-interline">
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
        )}

        <textarea
          onPaste={handlePaste}
          onKeyDownCapture={handleKeyDown}
          onChange={handleInputChange}
          ref={textAreaRef}
          id="onyx-chat-input-textarea"
          className={cn(
            "w-full outline-none bg-transparent resize-none placeholder:text-text-03 whitespace-normal break-word overscroll-contain overflow-y-auto p-spacing-paragraph"
          )}
          autoFocus
          style={{ scrollbarWidth: "thin" }}
          role="textarea"
          aria-multiline
          placeholder={
            selectedAssistant.id === 0
              ? `How can ${
                  settings?.enterpriseSettings?.application_name || "Onyx"
                } help you today`
              : `How can ${selectedAssistant.name} help you today`
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
          filterManager.timeRange ||
          filterManager.selectedDocumentSets.length > 0) && (
          <div className="flex gap-x-.5 px-2">
            <div className="flex gap-x-1 px-2 overflow-visible overflow-x-scroll items-end miniscroll">
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

        <div className="flex justify-between items-center w-full p-spacing-interline">
          <div className="flex flex-row items-center gap-spacing-inline">
            <FilePicker
              onFileClick={handleFileClick}
              onPickRecent={(file: ProjectFile) => {
                // Check if file with same ID already exists
                if (
                  !currentMessageFiles.some(
                    (existingFile) => existingFile.file_id === file.file_id
                  )
                ) {
                  setCurrentMessageFiles((prev) => [...prev, file]);
                }
              }}
              onUnpickRecent={(file: ProjectFile) => {
                setCurrentMessageFiles((prev) =>
                  prev.filter(
                    (existingFile) => existingFile.file_id !== file.file_id
                  )
                );
              }}
              recentFiles={allRecentFiles}
              handleUploadChange={handleUploadChange}
              trigger={
                <IconButton
                  icon={SvgPlusCircle}
                  tooltip="Attach Files"
                  tertiary
                />
              }
              selectedFileIds={currentMessageFiles.map((f) => f.id)}
            />
            {selectedAssistant.tools.length > 0 && (
              <ActionToggle
                selectedAssistant={selectedAssistant}
                filterManager={filterManager}
                availableSources={memoizedAvailableSources}
              />
            )}
            {showDeepResearch && (
              <SelectButton
                leftIcon={SvgHourglass}
                active={deepResearchEnabled}
                onClick={toggleDeepResearch}
                folded
                action
              >
                Deep Research
              </SelectButton>
            )}

            {forcedToolIds.length > 0 &&
              forcedToolIds.map((toolId) => {
                const tool = selectedAssistant.tools.find(
                  (tool) => tool.id === toolId
                );
                if (!tool) {
                  return null;
                }
                return (
                  <SelectButton
                    key={toolId}
                    leftIcon={getIconForAction(tool)}
                    onClick={() => {
                      setForcedToolIds((prev) =>
                        prev.filter((id) => id !== toolId)
                      );
                    }}
                    action
                    active
                  >
                    {tool.display_name}
                  </SelectButton>
                );
              })}
          </div>

          <div className="flex flex-row items-center gap-spacing-inline">
            <div data-testid="ChatInputBar/llm-popover-trigger">
              <LLMPopover
                llmManager={llmManager}
                requiresImageGeneration={false}
              />
            </div>
            <IconButton
              id="onyx-chat-input-send-button"
              icon={chatState === "input" ? SvgArrowUp : SvgStop}
              disabled={chatState === "input" && !message}
              onClick={() => {
                if (chatState == "streaming") {
                  stopGenerating();
                } else if (message) {
                  onSubmit();
                }
              }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

const ChatInputBar = React.memo(ChatInputBarInner);
ChatInputBar.displayName = "ChatInputBar";

export default ChatInputBar;
