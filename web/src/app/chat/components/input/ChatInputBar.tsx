import React, {
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { useRouter } from "next/navigation";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import LLMPopover from "@/refresh-components/popovers/LLMPopover";
import { FilterManager, LlmManager, useFederatedConnectors } from "@/lib/hooks";
import { useInputPrompts } from "@/lib/hooks/useInputPrompts";
import { useCCPairs } from "@/lib/hooks/useCCPairs";
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
import SvgHourglass from "@/icons/hourglass";
import SvgArrowUp from "@/icons/arrow-up";
import SvgStop from "@/icons/stop";
import FilePickerPopover from "@/refresh-components/popovers/FilePickerPopover";
import ActionsPopover from "@/refresh-components/popovers/ActionsPopover";
import SelectButton from "@/refresh-components/buttons/SelectButton";
import SvgPlusCircle from "@/icons/plus-circle";
import {
  getIconForAction,
  hasSearchToolsAvailable,
} from "@/app/chat/services/actionUtils";
import { useSlashCommands } from "@/app/chat/hooks/useSlashCommands";
import SlashCommandMenu from "@/app/chat/components/slash-commands/SlashCommandMenu";
import { SlashCommand } from "@/app/chat/components/slash-commands/types";
import { useAssistantPreferences } from "@/app/chat/hooks/useAssistantPreferences";
import { handleSlashCommandKeyDown } from "@/app/chat/components/input/keyboardHandlers";

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

export interface ChatInputBarProps {
  removeDocs: () => void;
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
  selectedAssistant: MinimalPersonaSnapshot | undefined;

  toggleDocumentSidebar: () => void;
  handleFileUpload: (files: File[]) => void;
  textAreaRef: React.RefObject<HTMLTextAreaElement | null>;
  filterManager: FilterManager;
  retrievalEnabled: boolean;
  deepResearchEnabled: boolean;
  setPresentingDocument?: (document: MinimalOnyxDocument) => void;
  toggleDeepResearch: () => void;
  disabled: boolean;
}

const ChatInputBar = React.memo(
  ({
    retrievalEnabled,
    removeDocs,
    toggleDocumentSidebar,
    filterManager,
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
    disabled,
  }: ChatInputBarProps) => {
    const router = useRouter();
    const { user } = useUser();
    const { forcedToolIds, setForcedToolIds, toggleForcedTool } =
      useForcedTools();
    const { currentMessageFiles, setCurrentMessageFiles } =
      useProjectsContext();
    const { assistantPreferences } = useAssistantPreferences();
    const { inputPrompts } = useInputPrompts();
    const fileInputRef = React.useRef<HTMLInputElement>(null);

    // ============================================================================
    // Slash Commands
    // ============================================================================
    const isAdmin = user?.role === "admin";

    const disabledToolIds = useMemo(() => {
      if (!selectedAssistant || !assistantPreferences) return [];
      return (
        assistantPreferences[selectedAssistant.id]?.disabled_tool_ids || []
      );
    }, [selectedAssistant, assistantPreferences]);

    const { executeCommand, getFilteredCommands } = useSlashCommands({
      isAdmin,
      tools: selectedAssistant?.tools || [],
      disabledToolIds,
      inputPrompts,
      shortcutsEnabled: user?.preferences?.shortcut_enabled ?? false,
    });

    const [slashMenuIndex, setSlashMenuIndex] = useState(0);

    const filteredSlashCommands = useMemo(() => {
      const trimmed = message.trim();
      // Only show slash commands when input starts with "/"
      if (!trimmed.startsWith("/")) return [];

      return getFilteredCommands(trimmed);
    }, [message, getFilteredCommands]);

    // Show unified menu when there are filtered commands
    const showSlashMenu = filteredSlashCommands.length > 0;

    useEffect(() => {
      setSlashMenuIndex(0);
    }, [filteredSlashCommands.length]);

    const commandContext = useMemo(
      () => ({
        clearInput: () => setMessage(""),
        startNewChat: () => router.push("/chat"),
        navigate: (path: string) => router.push(path),
        isAdmin: isAdmin ?? false,
        toggleForcedTool,
        setMessage, // For prompt commands to set input content
        triggerFileUpload: () => fileInputRef.current?.click(),
      }),
      [setMessage, router, isAdmin, toggleForcedTool]
    );

    const handleSelectSlashCommand = useCallback(
      (command: SlashCommand) => {
        executeCommand(command.command, commandContext);
        // Don't clear message here - let each command decide
        // (prompt commands set content, others clear)
      },
      [executeCommand, commandContext]
    );

    const handleSlashCommand = useCallback(
      (msg: string): boolean => {
        if (!msg.trim().startsWith("/")) return false;
        const executed = executeCommand(msg.trim(), commandContext);
        if (executed) {
          // Don't clear message here - let each command decide
          // (prompt commands set content, others clear)
          return true;
        }
        return false;
      },
      [executeCommand, commandContext]
    );

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
    useEffect(() => {
      const textarea = textAreaRef.current;
      if (textarea) {
        textarea.style.height = "0px"; // this is necessary in order to "reset" the scrollHeight
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

    const { ccPairs, isLoading: ccPairsLoading } = useCCPairs();
    const { data: federatedConnectorsData, isLoading: federatedLoading } =
      useFederatedConnectors();

    // Bottom controls are hidden until all data is loaded
    const controlsLoading =
      ccPairsLoading ||
      federatedLoading ||
      !selectedAssistant ||
      llmManager.isLoadingProviders;

    // Memoize availableSources to prevent unnecessary re-renders
    const memoizedAvailableSources = useMemo(
      () => [
        ...(ccPairs ?? []).map((ccPair) => ccPair.source),
        ...(federatedConnectorsData?.map((connector) => connector.source) ||
          []),
      ],
      [ccPairs, federatedConnectorsData]
    );

    const handleInputChange = useCallback(
      (event: React.ChangeEvent<HTMLTextAreaElement>) => {
        const text = event.target.value;
        setMessage(text);
      },
      [setMessage]
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

    // Detect if there are any non-image files to determine if images should be compact
    const shouldCompactImages = useMemo(() => {
      return hasNonImageFiles(currentMessageFiles);
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
      // Handle slash command menu navigation
      if (showSlashMenu) {
        const handled = handleSlashCommandKeyDown(e, {
          filteredSlashCommands,
          slashMenuIndex,
          setSlashMenuIndex,
          onSelectCommand: handleSelectSlashCommand,
          onEscape: () => setMessage(""),
        });
        if (handled) {
          e.stopPropagation(); // Prevent other handlers from running
          return;
        }
      }
    };

    return (
      <div className="relative w-full flex justify-center">
        {/* Hidden file input for /upload command */}
        <input
          ref={fileInputRef}
          type="file"
          className="hidden"
          multiple
          onChange={handleUploadChange}
          accept="*/*"
        />

        {/* Unified Slash Command Menu - includes prompts, navigation, and tools */}
        {showSlashMenu && (
          <SlashCommandMenu
            commands={filteredSlashCommands}
            selectedIndex={slashMenuIndex}
            onSelect={handleSelectSlashCommand}
          />
        )}

        <div
          id="onyx-chat-input"
          className={cn(
            "max-w-full w-[50rem] flex flex-col shadow-01 bg-background-neutral-00 rounded-16",
            disabled && "opacity-50 cursor-not-allowed pointer-events-none"
          )}
          aria-disabled={disabled}
        >
          {/* Attached Files */}
          {currentMessageFiles.length > 0 && (
            <div className="p-1 rounded-t-16 flex flex-wrap gap-2">
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
                !showSlashMenu &&
                !event.shiftKey &&
                !(event.nativeEvent as any).isComposing
              ) {
                event.preventDefault();
                if (message) {
                  // Check for slash commands first
                  if (handleSlashCommand(message)) {
                    return; // Command was handled, don't submit to chat
                  }
                  onSubmit();
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
                {/* Temporarily disabled - to re-enable, change false to showDeepResearch */}
                {false && showDeepResearch && (
                  <SelectButton
                    leftIcon={SvgHourglass}
                    onClick={toggleDeepResearch}
                    engaged={deepResearchEnabled}
                    action
                    folded
                    disabled={disabled}
                    className={disabled ? "bg-transparent" : ""}
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
                        className={disabled ? "bg-transparent" : ""}
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
                    // Check for slash commands first
                    if (handleSlashCommand(message)) {
                      return; // Command was handled, don't submit to chat
                    }
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
);
ChatInputBar.displayName = "ChatInputBar";

export default ChatInputBar;
