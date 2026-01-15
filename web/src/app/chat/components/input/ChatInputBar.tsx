import React, {
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { FiPlus } from "react-icons/fi";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import LLMPopover from "@/refresh-components/popovers/LLMPopover";
import { InputPrompt } from "@/app/chat/interfaces";
import { FilterManager, LlmManager, useFederatedConnectors } from "@/lib/hooks";
import usePromptShortcuts from "@/hooks/usePromptShortcuts";
import useCCPairs from "@/hooks/useCCPairs";
import { DocumentIcon2, FileIcon } from "@/components/icons/icons";
import { OnyxDocument, MinimalOnyxDocument } from "@/lib/search/interfaces";
import { ChatState } from "@/app/chat/interfaces";
import { useForcedTools } from "@/lib/hooks/useForcedTools";
import { CalendarIcon, XIcon } from "lucide-react";
import { getFormattedDateRangeString } from "@/lib/dateUtils";
import { truncateString, cn, hasNonImageFiles } from "@/lib/utils";
import { useUser } from "@/components/user/UserProvider";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import { useProjectsContext } from "@/app/chat/projects/ProjectsContext";
import { FileCard } from "@/app/chat/components/input/FileCard";
import {
  ProjectFile,
  UserFileStatus,
} from "@/app/chat/projects/projectsService";
import IconButton from "@/refresh-components/buttons/IconButton";
import FilePickerPopover from "@/refresh-components/popovers/FilePickerPopover";
import ActionsPopover from "@/refresh-components/popovers/ActionsPopover";
import SelectButton from "@/refresh-components/buttons/SelectButton";
import {
  getIconForAction,
  hasSearchToolsAvailable,
} from "@/app/chat/services/actionUtils";
import { SvgArrowUp, SvgHourglass, SvgPlusCircle, SvgStop } from "@opal/icons";

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
        "flex-none flex items-center px-1 bg-background-neutral-01 text-xs text-text-04 border border-border-01 rounded-08 box-border gap-x-1 h-6",
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

export interface ChatInputBarHandle {
  reset: () => void;
  focus: () => void;
}

export interface ChatInputBarProps {
  removeDocs: () => void;
  selectedDocuments: OnyxDocument[];
  initialMessage?: string;
  stopGenerating: () => void;
  onSubmit: (message: string) => void;
  onHeightChange?: (delta: number) => void;
  llmManager: LlmManager;
  chatState: ChatState;
  currentSessionFileTokenCount: number;
  availableContextTokens: number;

  // assistants
  selectedAssistant: MinimalPersonaSnapshot | undefined;

  toggleDocumentSidebar: () => void;
  handleFileUpload: (files: File[]) => void;
  filterManager: FilterManager;
  retrievalEnabled: boolean;
  deepResearchEnabled: boolean;
  setPresentingDocument?: (document: MinimalOnyxDocument) => void;
  toggleDeepResearch: () => void;
  disabled: boolean;
}

const ChatInputBar = React.memo(
  React.forwardRef<ChatInputBarHandle, ChatInputBarProps>(
    (
      {
        retrievalEnabled,
        removeDocs,
        toggleDocumentSidebar,
        filterManager,
        selectedDocuments,
        initialMessage = "",
        stopGenerating,
        onSubmit,
        onHeightChange,
        chatState,
        currentSessionFileTokenCount,
        availableContextTokens,
        // assistants
        selectedAssistant,

        handleFileUpload,
        llmManager,
        deepResearchEnabled,
        toggleDeepResearch,
        setPresentingDocument,
        disabled,
      },
      ref
    ) => {
      // Internal message state - kept local to avoid parent re-renders on every keystroke
      const [message, setMessage] = useState(initialMessage);
      const textAreaRef = useRef<HTMLTextAreaElement>(null);
      const containerRef = useRef<HTMLDivElement>(null);
      const previousHeightRef = useRef<number | null>(null);
      const onHeightChangeRef = useRef(onHeightChange);
      onHeightChangeRef.current = onHeightChange;

      // Expose reset and focus methods to parent via ref
      React.useImperativeHandle(ref, () => ({
        reset: () => {
          setMessage("");
        },
        focus: () => {
          textAreaRef.current?.focus();
        },
      }));
      const { user } = useUser();
      const { forcedToolIds, setForcedToolIds } = useForcedTools();
      const { currentMessageFiles, setCurrentMessageFiles } =
        useProjectsContext();

      const currentIndexingFiles = useMemo(() => {
        return currentMessageFiles.filter(
          (file) => file.status === UserFileStatus.PROCESSING
        );
      }, [currentMessageFiles]);

      const hasUploadingFiles = useMemo(() => {
        return currentMessageFiles.some(
          (file) => file.status === UserFileStatus.UPLOADING
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

      const combinedSettings = useContext(SettingsContext);

      // Auto-resize textarea based on content
      useEffect(() => {
        const textarea = textAreaRef.current;
        if (textarea) {
          textarea.style.height = "0px"; // this is necessary in order to "reset" the scrollHeight
          textarea.style.height = `${Math.min(
            textarea.scrollHeight,
            MAX_INPUT_HEIGHT
          )}px`;
        }
      }, [message]);

      useEffect(() => {
        if (initialMessage) {
          setMessage(initialMessage);
        }
      }, [initialMessage]);

      // Detect height changes and notify parent for scroll adjustment
      useEffect(() => {
        if (!containerRef.current) return;

        const observer = new ResizeObserver((entries) => {
          for (const entry of entries) {
            const newHeight = entry.contentRect.height;
            if (previousHeightRef.current !== null) {
              const delta = newHeight - previousHeightRef.current;
              if (delta !== 0) {
                onHeightChangeRef.current?.(delta);
              }
            }
            previousHeightRef.current = newHeight;
          }
        });

        observer.observe(containerRef.current);
        return () => observer.disconnect();
      }, []);

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

      const { promptShortcuts } = usePromptShortcuts();
      const { ccPairs, isLoading: ccPairsLoading } = useCCPairs();
      const { data: federatedConnectorsData, isLoading: federatedLoading } =
        useFederatedConnectors();

      // Bottom controls are hidden until all data is loaded
      const controlsLoading =
        ccPairsLoading ||
        federatedLoading ||
        !selectedAssistant ||
        llmManager.isLoadingProviders;
      const [showPrompts, setShowPrompts] = useState(false);

      // Memoize availableSources to prevent unnecessary re-renders
      const memoizedAvailableSources = useMemo(
        () => [
          ...ccPairs.map((ccPair) => ccPair.source),
          ...(federatedConnectorsData?.map((connector) => connector.source) ||
            []),
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
          promptShortcuts.filter(
            (prompt) =>
              prompt.active &&
              prompt.prompt.toLowerCase().startsWith(startFilterSlash)
          ),
        [promptShortcuts, startFilterSlash]
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

      const shouldCompactImages = useMemo(() => {
        return currentMessageFiles.length > 1;
      }, [currentMessageFiles]);

      // Check if the assistant has search tools available (internal search or web search)
      // AND if deep research is globally enabled in admin settings
      const showDeepResearch = useMemo(() => {
        const deepResearchGloballyEnabled =
          combinedSettings?.settings?.deep_research_enabled ?? true;
        return (
          deepResearchGloballyEnabled &&
          hasSearchToolsAvailable(selectedAssistant?.tools || [])
        );
      }, [
        selectedAssistant?.tools,
        combinedSettings?.settings?.deep_research_enabled,
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
        <>
          {user?.preferences?.shortcut_enabled && showPrompts && (
            <div className="text-sm absolute inset-x-0 top-0 w-full transform -translate-y-full">
              <div className="overflow-y-auto max-h-[200px] py-1.5 bg-background-neutral-01 border border-border-01 shadow-lg mx-2 px-1.5 mt-2 rounded z-10">
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

          <div
            ref={containerRef}
            id="onyx-chat-input"
            className={cn(
              "w-full flex flex-col shadow-01 bg-background-neutral-00 rounded-16",
              disabled && "opacity-50 cursor-not-allowed pointer-events-none"
            )}
            aria-disabled={disabled}
          >
            {/* Attached Files */}
            {currentMessageFiles.length > 0 && (
              <div className="p-2 rounded-t-16 flex flex-wrap gap-1">
                {currentMessageFiles.map((file) => (
                  <FileCard
                    key={file.id}
                    file={file}
                    removeFile={handleRemoveMessageFile}
                    hideProcessingState={hideProcessingState}
                    onFileClick={handleFileClick}
                    compactImages={shouldCompactImages}
                  />
                ))}
              </div>
            )}

            {/* Input area */}
            <textarea
              onPaste={handlePaste}
              onKeyDownCapture={handleKeyDown}
              onChange={handleInputChange}
              ref={textAreaRef}
              id="onyx-chat-input-textarea"
              className={cn(
                "w-full",
                "h-[44px]", // Fixed initial height to prevent flash - useEffect will adjust as needed
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
              placeholder="How can I help you today"
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
                    onSubmit(message);
                  }
                }
              }}
              suppressContentEditableWarning={true}
              disabled={disabled}
            />

            {/* Input area */}
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

            <div className="flex justify-between items-center w-full p-1 min-h-[40px]">
              {/* Bottom left controls */}
              <div className="flex flex-row items-center">
                {/* (+) button - always visible */}
                <FilePickerPopover
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
                  handleUploadChange={handleUploadChange}
                  trigger={(open) => (
                    <IconButton
                      icon={SvgPlusCircle}
                      tooltip="Attach Files"
                      tertiary
                      transient={open}
                      disabled={disabled}
                    />
                  )}
                  selectedFileIds={currentMessageFiles.map((f) => f.id)}
                />

                {/* Controls that load in when data is ready */}
                <div
                  className={cn(
                    "flex flex-row items-center",
                    controlsLoading && "invisible"
                  )}
                >
                  {selectedAssistant && selectedAssistant.tools.length > 0 && (
                    <ActionsPopover
                      selectedAssistant={selectedAssistant}
                      filterManager={filterManager}
                      availableSources={memoizedAvailableSources}
                      disabled={disabled}
                    />
                  )}
                  {showDeepResearch && (
                    <SelectButton
                      leftIcon={SvgHourglass}
                      onClick={toggleDeepResearch}
                      engaged={deepResearchEnabled}
                      action
                      folded
                      disabled={disabled}
                      className="bg-transparent"
                    >
                      Deep Research
                    </SelectButton>
                  )}

                  {selectedAssistant &&
                    forcedToolIds.length > 0 &&
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
                            setForcedToolIds(
                              forcedToolIds.filter((id) => id !== toolId)
                            );
                          }}
                          engaged
                          action
                          disabled={disabled}
                          className="bg-transparent"
                        >
                          {tool.display_name}
                        </SelectButton>
                      );
                    })}
                </div>
              </div>

              {/* Bottom right controls */}
              <div className="flex flex-row items-center gap-1">
                {/* LLM popover - loads when ready */}
                <div
                  data-testid="ChatInputBar/llm-popover-trigger"
                  className={cn(controlsLoading && "invisible")}
                >
                  <LLMPopover
                    llmManager={llmManager}
                    requiresImageGeneration={false}
                    disabled={disabled}
                  />
                </div>

                {/* Submit button - always visible */}
                <IconButton
                  id="onyx-chat-input-send-button"
                  icon={chatState === "input" ? SvgArrowUp : SvgStop}
                  disabled={
                    (chatState === "input" && !message) || hasUploadingFiles
                  }
                  onClick={() => {
                    if (chatState == "streaming") {
                      stopGenerating();
                    } else if (message) {
                      onSubmit(message);
                    }
                  }}
                />
              </div>
            </div>
          </div>
        </>
      );
    }
  )
);
ChatInputBar.displayName = "ChatInputBar";

export default ChatInputBar;
