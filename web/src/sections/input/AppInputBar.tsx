"use client";

import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import LineItem from "@/refresh-components/buttons/LineItem";
import { MinimalAgent } from "@/lib/agents/types";
import { InputPrompt } from "@/app/app/interfaces";
import { FilterManager, LlmManager, useFederatedConnectors } from "@/lib/hooks";
import usePromptShortcuts from "@/hooks/usePromptShortcuts";
import { useContentEditable } from "@/hooks/useContentEditable";
import useFilter from "@/hooks/useFilter";
import useCCPairs from "@/hooks/useCCPairs";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";
import { ChatState, MAX_QUEUED_MESSAGES } from "@/app/app/interfaces";
import { useQueuedMessageNavigation } from "@/hooks/useQueuedMessageNavigation";
import { useForcedTools } from "@/lib/hooks/useForcedTools";
import useAppFocus from "@/hooks/useAppFocus";
import { useDraft, draftKey } from "@/hooks/useDraft";
import { getPastedFilesIfNoText } from "@/lib/clipboard";
import PasteTilePopover from "@/sections/input/PasteTilePopover";
import { cn } from "@opal/utils";
import { Disabled } from "@opal/core";
import { useUser } from "@/providers/UserProvider";
import { useSettings } from "@/lib/settings/hooks";
import { useProjectsContext } from "@/providers/ProjectsContext";
import { FileCard } from "@/sections/cards/FileCard";
import { ProjectFile, UserFileStatus } from "@/lib/projects/types";
import FilePickerPopover from "@/refresh-components/popovers/FilePickerPopover";
import ActionsPopover from "@/refresh-components/popovers/ActionsPopover";
import {
  getIconForAction,
  hasSearchToolsAvailable,
} from "@/app/app/services/actionUtils";
import {
  SvgArrowUp,
  SvgGlobe,
  SvgHourglass,
  SvgMicrophone,
  SvgPaperclip,
  SvgPlus,
  SvgSearch,
  SvgStop,
  SvgX,
  SvgSimpleLoader,
} from "@opal/icons";
import { Button, SelectButton } from "@opal/components";
import { Popover } from "@opal/components";
import { useQueryController } from "@/providers/QueryControllerProvider";
import { Section } from "@/layouts/general-layouts";
import { Spacer } from "@opal/components";
import MicrophoneButton from "@/sections/input/MicrophoneButton";
import Waveform from "@/components/voice/Waveform";
import { useVoiceMode } from "@/providers/VoiceModeProvider";
import { useVoiceStatus } from "@/hooks/useVoiceStatus";
import {
  useCurrentQueuedMessages,
  useCurrentLatestMessageRenderComplete,
  useChatSessionStore,
} from "@/app/app/stores/useChatSessionStore";
import QueuedMessageBar from "@/sections/input/QueuedMessageBar";
import { handleInputNavKeys } from "@/sections/input/inputBarKeys";

export interface AppInputBarHandle {
  reset: () => void;
  focus: () => void;
}

export interface AppInputBarProps {
  initialMessage?: string;
  stopGenerating: () => void;
  onSubmit: (message: string) => void;
  llmManager: LlmManager;
  chatState: ChatState;
  currentSessionFileTokenCount: number;
  availableContextTokens: number;

  // agents
  selectedAgent: MinimalAgent | undefined;

  handleFileUpload: (files: File[]) => void;
  filterManager: FilterManager;
  deepResearchEnabled: boolean;
  setPresentingDocument?: (document: MinimalOnyxDocument) => void;
  toggleDeepResearch: () => void;
  isMultiModelActive?: boolean;
  disabled: boolean;
  awaitingPreferredSelection?: boolean;
  ref?: React.Ref<AppInputBarHandle>;
  // Side panel tab reading
  tabReadingEnabled?: boolean;
  currentTabUrl?: string | null;
  onToggleTabReading?: () => void;
}

const AppInputBar = React.memo(
  ({
    filterManager,
    initialMessage = "",
    stopGenerating,
    onSubmit,
    chatState,
    currentSessionFileTokenCount,
    availableContextTokens,
    selectedAgent,

    handleFileUpload,
    llmManager,
    deepResearchEnabled,
    toggleDeepResearch,
    isMultiModelActive,
    setPresentingDocument,
    disabled,
    awaitingPreferredSelection = false,
    ref,
    tabReadingEnabled,
    currentTabUrl,
    onToggleTabReading,
  }: AppInputBarProps) => {
    const [isRecording, setIsRecording] = useState(false);
    const [recordingCycleCount, setRecordingCycleCount] = useState(0);
    const [isMuted, setIsMuted] = useState(false);
    const [audioLevel, setAudioLevel] = useState(0);
    const stopRecordingRef = useRef<(() => Promise<string | null>) | null>(
      null
    );
    const setMutedRef = useRef<((muted: boolean) => void) | null>(null);
    const queuedMessages = useCurrentQueuedMessages();
    const latestMessageRenderComplete = useCurrentLatestMessageRenderComplete();
    const enqueueCurrentMessage = useChatSessionStore(
      (state) => state.enqueueCurrentMessage
    );
    const removeCurrentQueuedMessage = useChatSessionStore(
      (state) => state.removeCurrentQueuedMessage
    );
    const { user, isAdmin } = useUser();
    const isAutoSending = useRef(false);
    const inputWrapperRef = useRef<HTMLDivElement>(null);
    const {
      ref: inputRef,
      message,
      setMessage,
      clearMessage,
      handleInput,
      handleCompositionStart,
      handleCompositionEnd,
      pasteText,
      handleCopy,
      handleCut,
      setCursorToEnd,
      handleTileMouseDown,
      handleTileClick,
      handleTileKeyDown,
      tilePopover,
      dismissTilePopover,
      updateTileText,
      expandTile,
    } = useContentEditable({
      initialContent: initialMessage,
      wrapperRef: inputWrapperRef,
      pasteTilesEnabled: user?.preferences?.paste_as_tile ?? false,
    });

    // Keyboard navigation + highlight state for the queued-message bar
    // (shared with the Craft input bar).
    const queueNav = useQueuedMessageNavigation({
      messages: queuedMessages,
      inputIsEmpty: !message,
      onRemove: removeCurrentQueuedMessage,
      onEdit: setMessage,
    });

    const filesWrapperRef = useRef<HTMLDivElement>(null);
    const filesContentRef = useRef<HTMLDivElement>(null);
    const containerRef = useRef<HTMLDivElement>(null);
    const { state } = useQueryController();
    const isClassifying = state.phase === "classifying";
    const isSearchActive =
      state.phase === "searching" || state.phase === "search-results";
    const {
      stopTTS,
      isTTSPlaying,
      isManualTTSPlaying,
      isTTSLoading,
      isAwaitingAutoPlaybackStart,
      isTTSMuted,
      toggleTTSMute,
    } = useVoiceMode();
    const { sttEnabled } = useVoiceStatus();
    // Show mic button: always if STT configured, or greyed-out for admins to prompt setup
    const showMicButton = sttEnabled || isAdmin;
    const isVoicePlaybackActive =
      isTTSPlaying || isTTSLoading || isAwaitingAutoPlaybackStart;
    const isVoicePlaybackControllable = isVoicePlaybackActive && !isRecording;
    const isTTSActuallySpeaking = isTTSPlaying || isManualTTSPlaying;
    const appFocus = useAppFocus();
    const isNewSession = appFocus.isNewSession();
    const appMode = state.phase === "idle" ? state.appMode : undefined;
    const isSearchMode =
      (isNewSession && appMode === "search") || isSearchActive;

    // Keyed by chat session id, or "new" until the session is created.
    const chatSessionId = appFocus.isChat() ? appFocus.getId() : null;
    const chatDraftStorageKey = draftKey("chat", chatSessionId ?? "new");
    const {
      draft: chatDraft,
      loaded: chatDraftLoaded,
      save: saveChatDraft,
      clear: clearChatDraft,
    } = useDraft<string>({ key: chatDraftStorageKey });
    const draftSeededRef = useRef(false);
    const skipNextDraftSaveRef = useRef(false);
    const prevDraftKeyRef = useRef(chatDraftStorageKey);
    // Snapshot of message, read non-reactively in the restore effect so seeding
    // doesn't re-run on every keystroke.
    const messageRef = useRef(message);
    messageRef.current = message;

    useEffect(() => {
      draftSeededRef.current = false;
      // Clear the previous session's leftover text instead of leaking it into
      // this one.
      if (prevDraftKeyRef.current !== chatDraftStorageKey) {
        prevDraftKeyRef.current = chatDraftStorageKey;
        clearMessage();
      }
    }, [chatDraftStorageKey, clearMessage]);

    // Restore once read: a URL prompt wins and a non-empty input is never
    // clobbered.
    useEffect(() => {
      if (!chatDraftLoaded || draftSeededRef.current) return;
      draftSeededRef.current = true;
      if (chatDraft && !initialMessage && !messageRef.current) {
        // Skip the save effect's next run; it would fire with the stale empty
        // message and wipe what we just seeded.
        skipNextDraftSaveRef.current = true;
        setMessage(chatDraft);
      }
    }, [chatDraftLoaded, chatDraft, initialMessage, setMessage]);

    useEffect(() => {
      if (!chatDraftLoaded || !draftSeededRef.current) return;
      if (skipNextDraftSaveRef.current) {
        skipNextDraftSaveRef.current = false;
        return;
      }
      saveChatDraft(message);
    }, [message, chatDraftLoaded, saveChatDraft]);

    const handleRecordingChange = useCallback((nextIsRecording: boolean) => {
      setIsRecording((prevIsRecording) => {
        if (!prevIsRecording && nextIsRecording) {
          setRecordingCycleCount((count) => count + 1);
        }
        return nextIsRecording;
      });
    }, []);

    // Wrapper for onSubmit that stops TTS first to prevent overlapping voices
    const handleSubmit = useCallback(
      (text: string) => {
        stopTTS();
        onSubmit(text);
      },
      [stopTTS, onSubmit]
    );
    const submitMessage = useCallback(
      (text: string) => {
        if (!text.trim()) {
          return;
        }
        handleSubmit(text);
        clearChatDraft();
      },
      [handleSubmit, clearChatDraft]
    );

    // Expose reset and focus methods to parent via ref
    React.useImperativeHandle(ref, () => ({
      reset: () => {
        if (!isAutoSending.current) {
          clearMessage();
          clearChatDraft();
        }
      },
      focus: () => {
        inputRef.current?.focus();
        setCursorToEnd();
      },
    }));

    // Sync non-empty prop changes to internal state (e.g. NRFPage reads URL params
    // after mount). Intentionally skips empty strings — clearing is handled via the
    // imperative ref.reset() method, not by passing initialMessage="".
    useEffect(() => {
      if (initialMessage) {
        setMessage(initialMessage);
      }
    }, [initialMessage]); // eslint-disable-line react-hooks/exhaustive-deps
    const shouldShowRecordingWaveformBelow =
      isRecording &&
      !isVoicePlaybackActive &&
      (isNewSession || recordingCycleCount === 1);

    useEffect(() => {
      if (isNewSession && !initialMessage) {
        clearMessage();
      }
    }, [isNewSession, initialMessage]); // eslint-disable-line react-hooks/exhaustive-deps

    const { forcedToolIds, setForcedToolIds } = useForcedTools();
    const { currentMessageFiles, setCurrentMessageFiles, currentProjectId } =
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

    // A file isn't queryable until indexing completes, so gate send on it.
    const hasIndexingFiles = currentIndexingFiles.length > 0;

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

    const combinedSettingsData = useSettings();

    const prevChatStateRef = useRef(chatState);
    const prevAwaitingRef = useRef(awaitingPreferredSelection);
    const prevRenderCompleteRef = useRef(latestMessageRenderComplete);

    useEffect(() => {
      // "Ready" requires the backend to be idle AND the previous answer
      // to have finished drawing on screen. Without the render-complete
      // gate, a queued follow-up fires while the smooth-streaming
      // typewriter is still flushing the prior answer.
      const wasReady =
        prevChatStateRef.current === "input" &&
        !prevAwaitingRef.current &&
        prevRenderCompleteRef.current;
      const isReady =
        chatState === "input" &&
        !awaitingPreferredSelection &&
        latestMessageRenderComplete;

      prevChatStateRef.current = chatState;
      prevAwaitingRef.current = awaitingPreferredSelection;
      prevRenderCompleteRef.current = latestMessageRenderComplete;

      if (!wasReady && isReady && queuedMessages.length > 0) {
        const nextMessage = queuedMessages[0]!.text;
        isAutoSending.current = true;
        stopTTS();
        onSubmit(nextMessage);
        isAutoSending.current = false;
        removeCurrentQueuedMessage(0);
      }
    }, [
      chatState,
      awaitingPreferredSelection,
      latestMessageRenderComplete,
      queuedMessages,
      removeCurrentQueuedMessage,
      stopTTS,
      onSubmit,
    ]);

    // Animate attached files wrapper to its content height so CSS transitions
    // can interpolate between concrete pixel values (0px ↔ Npx).
    const showFiles = !isSearchMode && currentMessageFiles.length > 0;
    useEffect(() => {
      const wrapper = filesWrapperRef.current;
      const content = filesContentRef.current;
      if (!wrapper || !content) return;

      if (showFiles) {
        // Measure the inner content's actual height, then add padding (p-1 = 8px total)
        const PADDING = 8;
        wrapper.style.height = `${content.offsetHeight + PADDING}px`;
      } else {
        wrapper.style.height = "0px";
      }
    }, [showFiles, currentMessageFiles]);

    function handlePaste(event: React.ClipboardEvent) {
      if (disabled) return;
      const pastedFiles = getPastedFilesIfNoText(event.clipboardData);
      if (pastedFiles.length > 0) {
        event.preventDefault();
        handleFileUpload(pastedFiles);
        return;
      }

      event.preventDefault();
      const text = event.clipboardData.getData("text/plain");
      if (!text) return;

      pasteText(text);
    }

    const handleRemoveMessageFile = useCallback(
      (fileId: string) => {
        setCurrentMessageFiles((prev) => prev.filter((f) => f.id !== fileId));
      },
      [setCurrentMessageFiles]
    );

    const { activePromptShortcuts } = usePromptShortcuts();
    const { vectorDbEnabled } = combinedSettingsData;
    const { ccPairs, isLoading: ccPairsLoading } = useCCPairs(vectorDbEnabled);
    const { data: federatedConnectorsData, isLoading: federatedLoading } =
      useFederatedConnectors();

    // Bottom controls are hidden until all data is loaded
    const controlsLoading =
      ccPairsLoading ||
      federatedLoading ||
      !selectedAgent ||
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
      setMessage(prompt.content);
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

    const handleContentEditableInput = useCallback(
      (event: React.SyntheticEvent<HTMLDivElement>) => {
        const text = handleInput(event);
        if (text.startsWith("/")) {
          setShowPrompts(true);
          setPromptFilterQuery(text.slice(1));
        } else {
          hidePrompts();
          setPromptFilterQuery("");
        }
      },
      [handleInput, hidePrompts, setPromptFilterQuery]
    );

    // Determine if we should hide processing state based on context limits
    const hideProcessingState = useMemo(() => {
      if (currentMessageFiles.length > 0 && currentIndexingFiles.length > 0) {
        // token_count is null until indexing finishes; don't hide the
        // processing indicator while a file's size is still unknown.
        const allTokenCountsKnown = currentIndexingFiles.every(
          (file) => file.token_count !== null
        );
        if (!allTokenCountsKnown) {
          return false;
        }
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

    // Check if the agent has search tools available (internal search or web search)
    // AND if deep research is globally enabled in admin settings
    const showDeepResearch = useMemo(() => {
      const deepResearchGloballyEnabled =
        combinedSettingsData?.deep_research_enabled ?? true;
      const isProjectWorkflow = currentProjectId !== null;

      // TODO(@yuhong): Re-enable Deep Research in Projects workflow once it is fully supported.
      // https://linear.app/onyx-app/issue/ENG-3818/re-enable-deep-research-in-projects
      return (
        !isProjectWorkflow &&
        deepResearchGloballyEnabled &&
        hasSearchToolsAvailable(selectedAgent?.tools || [])
      );
    }, [
      selectedAgent?.tools,
      combinedSettingsData?.deep_research_enabled,
      currentProjectId,
    ]);

    function handleKeyDownForPromptShortcuts(
      e: React.KeyboardEvent<HTMLDivElement>
    ) {
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

    const chatControls = (
      <div
        {...(isSearchMode ? { inert: true } : {})}
        className={cn(
          "flex justify-between items-center w-full",
          isSearchMode
            ? "opacity-0 p-0 h-0 overflow-hidden pointer-events-none"
            : "opacity-100 p-1 h-11 pointer-events-auto",
          "transition-all duration-150"
        )}
      >
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
              <Button
                disabled={disabled}
                icon={SvgPaperclip}
                tooltip="Attach Files"
                interaction={open ? "hover" : "rest"}
                prominence="tertiary"
              />
            )}
            selectedFileIds={currentMessageFiles.map((f) => f.id)}
          />

          {/* Controls that load in when data is ready */}
          <div
            data-testid="actions-container"
            className={cn(
              "flex flex-row items-center",
              controlsLoading && "invisible"
            )}
          >
            {selectedAgent && selectedAgent.tools.length > 0 && (
              <ActionsPopover
                selectedAgent={selectedAgent}
                filterManager={filterManager}
                availableSources={memoizedAvailableSources}
                disabled={disabled}
              />
            )}
            {onToggleTabReading ? (
              <SelectButton
                disabled={disabled}
                icon={SvgGlobe}
                onClick={onToggleTabReading}
                state={tabReadingEnabled ? "selected" : "empty"}
              >
                {tabReadingEnabled
                  ? currentTabUrl
                    ? (() => {
                        try {
                          return new URL(currentTabUrl).hostname;
                        } catch {
                          return currentTabUrl;
                        }
                      })()
                    : "Reading tab..."
                  : "Read this tab"}
              </SelectButton>
            ) : (
              showDeepResearch && (
                <SelectButton
                  disabled={disabled || isMultiModelActive}
                  variant="select-light"
                  icon={SvgHourglass}
                  onClick={toggleDeepResearch}
                  state={deepResearchEnabled ? "selected" : "empty"}
                  foldable={!deepResearchEnabled}
                  tooltip={
                    isMultiModelActive
                      ? "Deep Research is disabled in multi-model mode"
                      : undefined
                  }
                >
                  Deep Research
                </SelectButton>
              )
            )}

            {selectedAgent &&
              forcedToolIds.length > 0 &&
              forcedToolIds.map((toolId) => {
                const tool = selectedAgent.tools.find(
                  (tool) => tool.id === toolId
                );
                if (!tool) {
                  return null;
                }
                return (
                  <Disabled disabled={disabled} key={toolId}>
                    <SelectButton
                      variant="select-light"
                      icon={getIconForAction(tool)}
                      onClick={() => {
                        setForcedToolIds(
                          forcedToolIds.filter((id) => id !== toolId)
                        );
                      }}
                      state="selected"
                    >
                      {tool.display_name}
                    </SelectButton>
                  </Disabled>
                );
              })}
          </div>
        </div>

        {/* Bottom right controls */}
        <div className="flex flex-row items-center gap-1">
          {showMicButton &&
            (sttEnabled ? (
              <MicrophoneButton
                onTranscription={(text) => setMessage(text)}
                disabled={disabled || chatState === "streaming"}
                autoSend={user?.preferences?.voice_auto_send ?? false}
                autoListen={user?.preferences?.voice_auto_playback ?? false}
                isNewSession={isNewSession}
                chatState={chatState}
                onRecordingChange={handleRecordingChange}
                stopRecordingRef={stopRecordingRef}
                currentMessage={message}
                onRecordingStart={() => {}}
                onAutoSend={(text) => {
                  submitMessage(text);
                }}
                onMuteChange={setIsMuted}
                setMutedRef={setMutedRef}
                onAudioLevel={setAudioLevel}
              />
            ) : (
              <Button
                disabled
                icon={SvgMicrophone}
                aria-label="Set up voice"
                prominence="tertiary"
                tooltip="Voice not configured. Set up in admin settings."
              />
            ))}

          <Button
            disabled={
              (chatState === "input" &&
                !isVoicePlaybackControllable &&
                !message) ||
              hasUploadingFiles ||
              hasIndexingFiles ||
              isClassifying
            }
            tooltip={
              hasUploadingFiles || hasIndexingFiles
                ? "Waiting for attached file(s) to finish processing"
                : undefined
            }
            id="onyx-chat-input-send-button"
            icon={
              isClassifying
                ? SvgSimpleLoader
                : (chatState !== "input" || awaitingPreferredSelection) &&
                    message.trim()
                  ? SvgArrowUp
                  : chatState === "streaming" || isVoicePlaybackControllable
                    ? SvgStop
                    : SvgArrowUp
            }
            onClick={() => {
              const canSubmitNormally =
                chatState === "input" && !awaitingPreferredSelection;
              if (!canSubmitNormally && message.trim()) {
                if (queuedMessages.length < MAX_QUEUED_MESSAGES) {
                  enqueueCurrentMessage(message.trim());
                  clearMessage();
                  // Drop the draft now; a reload could outrace the debounced
                  // empty-save.
                  clearChatDraft();
                }
              } else if (chatState == "streaming") {
                stopTTS({ manual: true });
                stopGenerating();
              } else if (isVoicePlaybackControllable) {
                stopTTS({ manual: true });
              } else if (message) {
                submitMessage(message);
              }
            }}
          />
        </div>
      </div>
    );

    return (
      <>
        <QueuedMessageBar
          messages={queuedMessages}
          highlightedIndex={queueNav.highlightedIndex}
          awaitingPreferredSelection={awaitingPreferredSelection}
          onDiscard={removeCurrentQueuedMessage}
          onHighlight={queueNav.setHighlightedIndex}
        />
        <Disabled disabled={disabled} allowClick>
          <div
            ref={containerRef}
            id="onyx-chat-input"
            className={cn(
              "relative w-full flex flex-col shadow-box-01 bg-background-neutral-00 rounded-16"
              // # Note (from @raunakab):
              //
              // `shadow-box-01` extends ~14px below the element (2px offset + 12px blur).
              // Because the content area in `Root` (app-layouts.tsx) uses `overflow-auto`,
              // shadows that exceed the container bounds are clipped.
              //
              // The 14px breathing room is now applied externally via animated spacer
              // divs in `AppPage.tsx` (above and below the AppInputBar) so that the
              // spacing can transition smoothly when switching between search and chat
              // modes. See the corresponding note there for details.
            )}
          >
            {/* Voice waveform overlay (positioned outside normal flow to avoid resizing input) */}
            {isTTSActuallySpeaking ? (
              <div className="absolute bottom-full mb-1 left-1 z-10">
                <Waveform
                  variant="speaking"
                  isActive={isTTSActuallySpeaking}
                  isMuted={isTTSMuted}
                  onMuteToggle={toggleTTSMute}
                />
              </div>
            ) : isRecording &&
              !isVoicePlaybackActive &&
              !shouldShowRecordingWaveformBelow ? (
              <div className="absolute bottom-full mb-1 left-1 right-1 z-10">
                <Waveform
                  variant="recording"
                  isActive={isRecording}
                  isMuted={isMuted}
                  audioLevel={audioLevel}
                  onMuteToggle={() => {
                    setMutedRef.current?.(!isMuted);
                  }}
                />
              </div>
            ) : null}

            {/* Attached Files */}
            <div
              ref={filesWrapperRef}
              {...(!showFiles ? { inert: true } : {})}
              className={cn(
                "transition-all duration-150",
                showFiles
                  ? "opacity-100 p-1"
                  : "opacity-0 p-0 overflow-hidden pointer-events-none"
              )}
            >
              <div ref={filesContentRef} className="flex flex-wrap gap-1">
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
            </div>

            <div className="flex flex-row items-center w-full">
              <Popover
                open={user?.preferences?.shortcut_enabled && showPrompts}
                onOpenChange={setShowPrompts}
              >
                <Popover.Anchor asChild>
                  <div
                    ref={inputWrapperRef}
                    className="px-3 py-2 flex-1 flex h-11 overflow-hidden"
                  >
                    <div
                      ref={inputRef}
                      id="onyx-chat-input-textbox"
                      role="textbox"
                      aria-label="Message input"
                      contentEditable={!disabled}
                      suppressContentEditableWarning
                      onPaste={handlePaste}
                      onCopy={handleCopy}
                      onCut={handleCut}
                      onMouseDown={handleTileMouseDown}
                      onClick={handleTileClick}
                      onBlur={() => queueNav.setHighlightedIndex(null)}
                      onKeyDownCapture={handleKeyDownForPromptShortcuts}
                      onInput={handleContentEditableInput}
                      onCompositionStart={handleCompositionStart}
                      onCompositionEnd={handleCompositionEnd}
                      className="p-[2px] w-full h-full outline-hidden bg-transparent whitespace-pre-wrap wrap-break-word overflow-y-auto"
                      tabIndex={disabled ? -1 : 0}
                      style={{
                        scrollbarWidth: "thin",
                        scrollbarColor: "var(--border-02) transparent",
                      }}
                      aria-multiline={true}
                      aria-disabled={disabled}
                      aria-placeholder="How can I help you today?"
                      data-placeholder={
                        queuedMessages.length > 0 && !message
                          ? "Press up to edit queued messages"
                          : isRecording
                            ? "Listening..."
                            : isVoicePlaybackActive
                              ? "Onyx is speaking..."
                              : isSearchMode
                                ? "Search connected sources"
                                : "How can I help you today?"
                      }
                      data-empty={!message ? "" : undefined}
                      onKeyDown={(event) => {
                        if (
                          handleInputNavKeys(event, queueNav, handleTileKeyDown)
                        )
                          return;

                        // Enter to submit or queue (Shift+Enter falls through
                        // to browser default: inserts <br>).
                        if (
                          event.key === "Enter" &&
                          !showPrompts &&
                          !event.shiftKey &&
                          !(event.nativeEvent as any).isComposing
                        ) {
                          event.preventDefault();
                          const canSubmitNormally =
                            chatState === "input" &&
                            !awaitingPreferredSelection;
                          if (canSubmitNormally) {
                            if (
                              message &&
                              !disabled &&
                              !isClassifying &&
                              !hasUploadingFiles
                            ) {
                              submitMessage(message);
                            }
                          } else if (
                            message.trim() &&
                            !disabled &&
                            !isClassifying &&
                            !hasUploadingFiles &&
                            queuedMessages.length < MAX_QUEUED_MESSAGES
                          ) {
                            enqueueCurrentMessage(message.trim());
                            clearMessage();
                            // Drop the draft now; a reload could outrace the
                            // debounced empty-save.
                            clearChatDraft();
                          }
                        }
                      }}
                    />
                  </div>
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
                        selected={
                          tabbingIconIndex === sortedFilteredPrompts.length
                        }
                        emphasized={
                          tabbingIconIndex === sortedFilteredPrompts.length
                        }
                      >
                        Create New Prompt
                      </LineItem>,
                    ]}
                  </Popover.Menu>
                </Popover.Content>
              </Popover>

              {isSearchMode && (
                <Section flexDirection="row" width="fit" gap={0}>
                  <Button
                    disabled={!message || isClassifying}
                    icon={SvgX}
                    onClick={() => clearMessage()}
                    prominence="tertiary"
                  />
                  <Button
                    disabled={!message || isClassifying || hasUploadingFiles}
                    id="onyx-chat-input-send-button"
                    icon={isClassifying ? SvgSimpleLoader : SvgSearch}
                    onClick={() => {
                      if (chatState == "streaming") {
                        stopGenerating();
                      } else if (message) {
                        submitMessage(message);
                      }
                    }}
                    prominence="tertiary"
                  />
                  <Spacer orientation="horizontal" rem={0.25} />
                </Section>
              )}
            </div>

            {chatControls}

            {/* First recording cycle waveform below input */}
            {shouldShowRecordingWaveformBelow && (
              <div className="absolute top-full mt-1 left-1 right-1 z-10">
                <Waveform
                  variant="recording"
                  isActive={isRecording}
                  isMuted={isMuted}
                  audioLevel={audioLevel}
                  onMuteToggle={() => {
                    setMutedRef.current?.(!isMuted);
                  }}
                />
              </div>
            )}
            {tilePopover && (
              <PasteTilePopover
                text={tilePopover.text}
                tileElement={tilePopover.tile}
                onDismiss={dismissTilePopover}
                onTextChange={updateTileText}
                onExpand={() => expandTile(tilePopover.tile)}
              />
            )}
          </div>
        </Disabled>
      </>
    );
  }
);
AppInputBar.displayName = "AppInputBar";

export default AppInputBar;
