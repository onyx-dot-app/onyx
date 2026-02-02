"use client";

import React, {
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import LineItem from "@/refresh-components/buttons/LineItem";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import LLMPopover from "@/refresh-components/popovers/LLMPopover";
import { InputPrompt } from "@/app/app/interfaces";
import { FilterManager, LlmManager, useFederatedConnectors } from "@/lib/hooks";
import usePromptShortcuts from "@/hooks/usePromptShortcuts";
import useFilter from "@/hooks/useFilter";
import useCCPairs from "@/hooks/useCCPairs";
import { OnyxDocument, MinimalOnyxDocument } from "@/lib/search/interfaces";
import { ChatState } from "@/app/app/interfaces";
import { useForcedTools } from "@/lib/hooks/useForcedTools";
import { getFormattedDateRangeString } from "@/lib/dateUtils";
import { truncateString, cn } from "@/lib/utils";
import { useUser } from "@/providers/UserProvider";
import { SettingsContext } from "@/providers/SettingsProvider";
import { useProjectsContext } from "@/providers/ProjectsContext";
import { FileCard } from "@/sections/cards/FileCard";
import {
  ProjectFile,
  UserFileStatus,
} from "@/app/app/projects/projectsService";
import IconButton from "@/refresh-components/buttons/IconButton";
import FilePickerPopover from "@/refresh-components/popovers/FilePickerPopover";
import ActionsPopover from "@/refresh-components/popovers/ActionsPopover";
import SelectButton from "@/refresh-components/buttons/SelectButton";
import {
  getIconForAction,
  hasSearchToolsAvailable,
} from "@/app/app/services/actionUtils";
import {
  SvgArrowUp,
  SvgCalendar,
  SvgFiles,
  SvgFileText,
  SvgHourglass,
  SvgPlus,
  SvgPlusCircle,
  SvgStop,
  SvgX,
} from "@opal/icons";
import Popover from "@/refresh-components/Popover";

const LINE_HEIGHT = 24;
const MIN_INPUT_HEIGHT = 44;
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
        <SvgX
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
  ref?: React.Ref<ChatInputBarHandle>;
}

const ChatInputBar = React.memo(
  ({
    retrievalEnabled,
    removeDocs,
    toggleDocumentSidebar,
    filterManager,
    selectedDocuments,
    initialMessage = "",
    stopGenerating,
    onSubmit,
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
    ref,
  }: ChatInputBarProps) => {
    // Internal message state - kept local to avoid parent re-renders on every keystroke
    const [message, setMessage] = useState(initialMessage);
    const textAreaRef = useRef<HTMLTextAreaElement>(null);
    const containerRef = useRef<HTMLDivElement>(null);
    const { user } = useUser();

    // Expose reset and focus methods to parent via ref
    React.useImperativeHandle(ref, () => ({
      reset: () => {
        setMessage("");
      },
      focus: () => {
        textAreaRef.current?.focus();
      },
    }));
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

    // Track previous message to detect when lines might decrease
    const prevMessageRef = useRef("");

    // Auto-resize textarea based on content
    useEffect(() => {
      const textarea = textAreaRef.current;
      if (textarea) {
        const prevLineCount = (prevMessageRef.current.match(/\n/g) || [])
          .length;
        const currLineCount = (message.match(/\n/g) || []).length;
        const lineRemoved = currLineCount < prevLineCount;
        prevMessageRef.current = message;

        if (message.length === 0) {
          textarea.style.height = `${MIN_INPUT_HEIGHT}px`;
          return;
        } else if (lineRemoved) {
          const linesRemoved = prevLineCount - currLineCount;
          textarea.style.height = `${Math.max(
            MIN_INPUT_HEIGHT,
            Math.min(
              textarea.scrollHeight - LINE_HEIGHT * linesRemoved,
              MAX_INPUT_HEIGHT
            )
          )}px`;
        } else {
          textarea.style.height = `${Math.min(
            textarea.scrollHeight,
            MAX_INPUT_HEIGHT
          )}px`;
        }
      }
    }, [message]);

    useEffect(() => {
      if (initialMessage) {
        setMessage(initialMessage);
      }
    }, [initialMessage]);

    function handlePaste(event: React.ClipboardEvent) {
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
    }

    const handleRemoveMessageFile = useCallback(
      (fileId: string) => {
        setCurrentMessageFiles((prev) => prev.filter((f) => f.id !== fileId));
      },
      [setCurrentMessageFiles]
    );

    const { activePromptShortcuts } = usePromptShortcuts();
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

    const [tabbingIconIndex, setTabbingIconIndex] = useState(0);

    const hidePrompts = useCallback(() => {
      setTimeout(() => {
        setShowPrompts(false);
      }, 50);
      setTabbingIconIndex(0);
    }, []);

    function updateInputPrompt(prompt: InputPrompt) {
      hidePrompts();
      setMessage(`${prompt.content}`);
    }

    const { filtered: filteredPrompts, setQuery: setPromptFilterQuery } =
      useFilter(activePromptShortcuts, (prompt) => prompt.prompt);

    // Memoize sorted prompts to avoid re-sorting on every render
    const sortedFilteredPrompts = useMemo(
      () => [...filteredPrompts].sort((a, b) => a.id - b.id),
      [filteredPrompts]
    );

    // Reset tabbingIconIndex when filtered prompts change to avoid out-of-bounds
    useEffect(() => {
      setTabbingIconIndex(0);
    }, [filteredPrompts]);

    const handlePromptInput = useCallback(
      (text: string) => {
        if (text.startsWith("/")) {
          setShowPrompts(true);
        } else {
          hidePrompts();
        }
      },
      [hidePrompts]
    );

    const handleInputChange = useCallback(
      (event: React.ChangeEvent<HTMLTextAreaElement>) => {
        const text = event.target.value;
        setMessage(text);
        handlePromptInput(text);

        const promptFilterQuery = text.startsWith("/") ? text.slice(1) : "";
        setPromptFilterQuery(promptFilterQuery);
      },
      [setMessage, handlePromptInput, setPromptFilterQuery]
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

    function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
      if (!user?.preferences?.shortcut_enabled || !showPrompts) return;

      if (e.key === "Enter") {
        e.preventDefault();
        if (tabbingIconIndex === sortedFilteredPrompts.length) {
          // "Create a new prompt" is selected
          window.open("/app/settings/chat-preferences", "_self");
        } else {
          const selectedPrompt = sortedFilteredPrompts[tabbingIconIndex];
          if (selectedPrompt) {
            updateInputPrompt(selectedPrompt);
          }
        }
      } else if (e.key === "Tab" && e.shiftKey) {
        // Shift+Tab: cycle backward
        e.preventDefault();
        setTabbingIconIndex((prev) => Math.max(prev - 1, 0));
      } else if (e.key === "Tab") {
        // Tab: cycle forward
        e.preventDefault();
        setTabbingIconIndex((prev) =>
          Math.min(prev + 1, sortedFilteredPrompts.length)
        );
      } else if (e.key === "ArrowDown") {
        e.preventDefault();
        setTabbingIconIndex((prev) =>
          Math.min(prev + 1, sortedFilteredPrompts.length)
        );
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setTabbingIconIndex((prev) => Math.max(prev - 1, 0));
      }
    }

    return (
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
        <Popover
          open={user?.preferences?.shortcut_enabled && showPrompts}
          onOpenChange={setShowPrompts}
        >
          <Popover.Anchor asChild>
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
          </Popover.Anchor>

          <Popover.Content
            side="top"
            align="start"
            onOpenAutoFocus={(e) => e.preventDefault()}
            width="xl"
          >
            <Popover.Menu>
              {[
                ...sortedFilteredPrompts.map((prompt, index) => (
                  <LineItem
                    key={prompt.id}
                    selected={tabbingIconIndex === index}
                    emphasized={tabbingIconIndex === index}
                    description={prompt.content?.trim()}
                    onClick={() => updateInputPrompt(prompt)}
                  >
                    {prompt.prompt}
                  </LineItem>
                )),
                sortedFilteredPrompts.length > 0 ? null : undefined,
                <LineItem
                  key="create-new"
                  href="/app/settings/chat-preferences"
                  icon={SvgPlus}
                  selected={tabbingIconIndex === sortedFilteredPrompts.length}
                  emphasized={tabbingIconIndex === sortedFilteredPrompts.length}
                >
                  Create New Prompt
                </LineItem>,
              ]}
            </Popover.Menu>
          </Popover.Content>
        </Popover>

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
                  icon={<SvgCalendar size={12} />}
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
                    icon={<SvgFiles size={16} />}
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
                  icon={<SvgFileText size={16} />}
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
    );
  }
);
ChatInputBar.displayName = "ChatInputBar";

export default ChatInputBar;
