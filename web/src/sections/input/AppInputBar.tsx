"use client";

import Keycap from "@/refresh-components/Keycap";
import useBrowserInfo from "@/hooks/useBrowserInfo";

import { useNavigation } from "@opal/navigation";
import { Section } from "@opal/layouts";
import { IconLoader } from "@opal/loaders";
import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslations } from "next-intl";
import { MinimalAgent } from "@/lib/agents/types";
import { InputPrompt } from "@/app/app/types";
import { LlmManager } from "@/lib/hooks";
import usePromptShortcuts from "@/hooks/usePromptShortcuts";
import { useContentEditable } from "@/hooks/useContentEditable";
import useFilter from "@/hooks/useFilter";
import { useAvailableSources } from "@/lib/connectors/hooks";
import { MinimalOnyxDocument } from "@/lib/search/types";
import { ChatState } from "@/app/app/types";
import { useQueuedMessageNavigation } from "@/hooks/useQueuedMessageNavigation";
import type { ToolConfigurationHandle } from "@/lib/tools/hooks";
import { effectiveChatPreferredToolId } from "@/lib/plugins/chat";
import type { MemberPlugin } from "@/lib/plugins/member";
import { useAppPosition } from "@/lib/navigation/hooks";
import { settleChatSession } from "@/lib/chat/settleChatSession";
import type {
  ChatSessionQueue,
  ComposedMessage,
  PendingChatMessage,
  UnsentMessage,
} from "@/lib/chat/types";
import { useDraft, draftKey, readDraft, writeDraft } from "@/hooks/useDraft";
import { getPastedFilesIfNoText } from "@/lib/clipboard";
import PasteTilePopover from "@/sections/input/PasteTilePopover";
import EntryPickerPopover from "@/sections/input/EntryPickerPopover";
import { useChatSkills, useEntryPicker } from "@/lib/skills/hooks";
import {
  flattenSections,
  type PickerEntry,
  type PickerSections,
} from "@/lib/skills/picker";
import { MENTION_TRIGGER } from "@/lib/chat/mentions";
import { cn } from "@opal/utils";
import { firstStrongTextDir } from "@/lib/rehypeDirection";
import { Disabled } from "@opal/core";
import { useUser } from "@/providers/UserProvider";
import { useSettings } from "@/lib/settings/hooks";
import { useProjectsContext } from "@/lib/projects/providers";
import { useActiveProject, useProjects } from "@/lib/projects/hooks";
import { FileCard } from "@/sections/cards/FileCard";
import { ProjectFile } from "@/lib/projects/types";
import { isFilePending } from "@/lib/projects/utils";
import FilePickerPopover from "@/refresh-components/popovers/FilePickerPopover";
import { ToolsPopover } from "@/lib/tools/components";
import MCPConnectionPrompt from "@/lib/mcp/components/MCPConnectionPrompt";
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
  SvgRefreshCw,
} from "@opal/icons";
import {
  Button,
  LineItemButton,
  Popover,
  SelectButton,
  Spacer,
  Text,
} from "@opal/components";
import { useQueryController } from "@/providers/QueryControllerProvider";
import { useIncognito } from "@/providers/IncognitoProvider";
import MicrophoneButton from "@/sections/input/MicrophoneButton";
import Waveform from "@/components/voice/Waveform";
import { useVoiceMode } from "@/providers/VoiceModeProvider";
import { useVoiceStatus } from "@/hooks/useVoiceStatus";
import {
  useChatSessionStore,
  useCurrentResponseStopped,
} from "@/app/app/stores/useChatSessionStore";
import QueuedMessageBar from "@/sections/input/QueuedMessageBar";
import { handleInputNavKeys } from "@/sections/input/inputBarKeys";

export interface AppInputBarHandle {
  reset: () => void;
  /** Puts back a question that failed to send, unless a newer draft exists. */
  restore: (unsent: UnsentMessage) => void;
  focus: () => void;
}

export interface AppInputBarProps {
  initialMessage?: string;
  stopGenerating: () => void;
  onSubmit: (composed: ComposedMessage) => void;
  llmManager: LlmManager;
  chatState: ChatState;

  // agents
  activeAgent: MinimalAgent | undefined;
  memberPlugins?: readonly MemberPlugin[];

  handleFileUpload: (files: File[]) => void;
  deepResearchEnabled: boolean;
  setPresentingDocument?: (document: MinimalOnyxDocument) => void;
  toggleDeepResearch: () => void;
  isMultiModelActive?: boolean;
  disabled: boolean;
  /**
   * Owned by the surface rather than read here, because the send path reads
   * the same one and two instances would drift.
   */
  toolConfiguration: ToolConfigurationHandle;
  ref?: React.Ref<AppInputBarHandle>;
  // Side panel tab reading
  tabReadingEnabled?: boolean;
  currentTabUrl?: string | null;
  onToggleTabReading?: () => void;
  /** Pending input of the current chat; a disabled queue makes input wait for the response. */
  queue: ChatSessionQueue;
}

// Older drafts are plain text.
type StoredChatDraft = ComposedMessage | string;

function toChatDraft(draft: StoredChatDraft): ComposedMessage {
  return typeof draft === "string" ? { message: draft, mentions: [] } : draft;
}

function isChatDraftEmpty(draft: StoredChatDraft): boolean {
  return !toChatDraft(draft).message.trim();
}

const AppInputBar = React.memo(
  ({
    initialMessage = "",
    stopGenerating,
    onSubmit,
    chatState,
    activeAgent,
    memberPlugins,
    handleFileUpload,
    llmManager,
    deepResearchEnabled,
    toggleDeepResearch,
    isMultiModelActive,
    setPresentingDocument,
    disabled,
    toolConfiguration,
    ref,
    tabReadingEnabled,
    currentTabUrl,
    onToggleTabReading,
    queue,
  }: AppInputBarProps) => {
    const t = useTranslations("chat.input");
    const { incognitoEnabled } = useIncognito();
    const [isRecording, setIsRecording] = useState(false);
    const [recordingCycleCount, setRecordingCycleCount] = useState(0);
    const [isMuted, setIsMuted] = useState(false);
    const [audioLevel, setAudioLevel] = useState(0);
    const stopRecordingRef = useRef<(() => Promise<string | null>) | null>(
      null
    );
    const setMutedRef = useRef<((muted: boolean) => void) | null>(null);
    const currentSessionId = useChatSessionStore(
      (state) => state.currentSessionId
    );
    const [checkingSessions, setCheckingSessions] = useState<Set<string>>(
      () => new Set()
    );
    const isCheckingCompletion =
      currentSessionId !== null && checkingSessions.has(currentSessionId);
    const responding = chatState === "loading" || chatState === "streaming";
    // Once the stop packet arrives, Stop would reach a finished stream.
    const responseStopped = useCurrentResponseStopped();
    const canStopGeneration = responding && !responseStopped;
    const tReadiness = useTranslations("chat.readiness");
    const queuedMessages = queue.messages;
    // Typing during an edit's withdrawal would collide with the returned text.
    const [editWithdrawalSession, setEditWithdrawalSession] = useState<
      string | null
    >(null);
    const withdrawingForEdit =
      editWithdrawalSession !== null &&
      editWithdrawalSession === currentSessionId;
    const { user, isAdmin } = useUser();
    const { isMac } = useBrowserInfo();
    const sendDelivery = user?.preferences.interrupt_on_send
      ? "interrupt"
      : "send";
    const inputWrapperRef = useRef<HTMLDivElement>(null);
    const {
      ref: inputRef,
      message,
      mentions,
      setMessage,
      clearMessage,
      insertMentionTile,
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

    // Something is mentioned only when picked from the `@` menu, which puts a
    // mention tile in the input. The tiles are the mentions: undo, cut and
    // code that replaces the text all change them with the text.
    const composed = useMemo(
      (): ComposedMessage => ({ message, mentions }),
      [message, mentions]
    );
    const chatSkills = useChatSkills();
    const insertMention = useCallback(
      (entry: PickerEntry, token: string) => {
        // Each mention kind maps its picker entry kind; chat mentions skills.
        if (entry.kind === "skill")
          insertMentionTile({ type: "skill", name: entry.slug }, token);
      },
      [insertMentionTile]
    );
    const mentionPicker = useEntryPicker({
      onSelect: insertMention,
      trigger: MENTION_TRIGGER,
    });
    // One section per mention source, as in the Craft picker.
    const mentionSections = useMemo((): PickerSections => {
      const query = mentionPicker.query.toLowerCase();
      return {
        skills: chatSkills.filter((skill) =>
          skill.name.toLowerCase().startsWith(query)
        ),
        apps: [],
        mcpServers: [],
      };
    }, [chatSkills, mentionPicker.query]);
    // While open, the mention picker wins over the `/` prompt shortcuts popover.
    const mentionPickerOpen =
      mentionPicker.open && flattenSections(mentionSections).length > 0;

    // Clearing or replacing the input in code fires no input event.
    useEffect(() => {
      if (!message) mentionPicker.reset();
    }, [message, mentionPicker.reset]);

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
    const appPosition = useAppPosition();
    const navigation = useNavigation();
    const isNewSession = appPosition.isNewSession();
    const appMode = state.phase === "idle" ? state.appMode : undefined;
    const isSearchMode =
      (isNewSession && appMode === "search") || isSearchActive;
    const combinedSettingsData = useSettings();

    const activePlaceholder =
      queuedMessages.length > 0 && !message
        ? t("appInputBar.input.queuedPlaceholder")
        : isRecording
          ? t("appInputBar.input.listeningPlaceholder")
          : isVoicePlaybackActive
            ? t("appInputBar.input.speakingPlaceholder", {
                appName: combinedSettingsData.appName,
              })
            : isSearchMode
              ? t("appInputBar.input.searchPlaceholder")
              : t("appInputBar.input.placeholder");

    // Keyed by chat session id, or "new" until the session is created.
    const chatSessionId = appPosition.chat();
    const chatDraftStorageKey = draftKey("chat", chatSessionId ?? "new");
    const {
      draft: chatDraft,
      loaded: chatDraftLoaded,
      save: saveChatDraft,
      clear: clearChatDraft,
    } = useDraft<StoredChatDraft>({
      key: chatDraftStorageKey,
      isEmpty: isChatDraftEmpty,
    });
    const draftSeededRef = useRef(false);
    const skipNextDraftSaveRef = useRef(false);
    const prevDraftKeyRef = useRef(chatDraftStorageKey);
    // Snapshot of the input, read non-reactively in the restore effect so
    // seeding doesn't re-run on every keystroke, and after awaits.
    const composedRef = useRef(composed);
    const isRecordingRef = useRef(isRecording);
    // Text returned after an unmount goes to the chat's draft instead.
    const mountedRef = useRef(true);
    useEffect(() => {
      mountedRef.current = true;
      return () => {
        mountedRef.current = false;
      };
    }, []);

    useEffect(() => {
      composedRef.current = composed;
    }, [composed]);

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
      if (chatDraft && !initialMessage && !composedRef.current.message) {
        // Skip the save effect's next run; it would fire with the stale empty
        // message and wipe what we just seeded.
        skipNextDraftSaveRef.current = true;
        const draft = toChatDraft(chatDraft);
        setMessage(draft.message, draft.mentions);
      }
    }, [chatDraftLoaded, chatDraft, initialMessage, setMessage]);

    useEffect(() => {
      if (!chatDraftLoaded || !draftSeededRef.current) return;
      if (skipNextDraftSaveRef.current) {
        skipNextDraftSaveRef.current = false;
        return;
      }
      saveChatDraft(composed);
    }, [composed, chatDraftLoaded, saveChatDraft]);

    const handleRecordingChange = useCallback((nextIsRecording: boolean) => {
      const wasRecording = isRecordingRef.current;
      isRecordingRef.current = nextIsRecording;
      if (!wasRecording && nextIsRecording) {
        setRecordingCycleCount((count) => count + 1);
      }
      setIsRecording(nextIsRecording);
    }, []);

    const submitMessage = useCallback(
      (submitted: ComposedMessage) => {
        if (chatState !== "input" || !submitted.message.trim()) {
          return;
        }
        // Stop TTS first to prevent overlapping voices.
        stopTTS();
        onSubmit(submitted);
        clearChatDraft();
      },
      [chatState, stopTTS, onSubmit, clearChatDraft]
    );

    const { currentMessageFiles, setCurrentMessageFiles } =
      useProjectsContext();

    // Expose reset and focus methods to parent via ref
    React.useImperativeHandle(ref, () => ({
      reset: () => {
        clearMessage();
        clearChatDraft();
      },
      restore: (unsent: UnsentMessage) => {
        // Keep a draft the user started while the failed send was pending.
        if (message.trim() || currentMessageFiles.length > 0) return;
        setMessage(unsent.message, unsent.mentions);
        setCurrentMessageFiles(unsent.files);
        setCursorToEnd();
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
    }, [initialMessage]);
    const shouldShowRecordingWaveformBelow =
      isRecording &&
      !isVoicePlaybackActive &&
      (isNewSession || recordingCycleCount === 1);

    useEffect(() => {
      if (isNewSession && !initialMessage) {
        clearMessage();
      }
    }, [isNewSession, initialMessage]);

    const { clearPreferredTool } = toolConfiguration;
    const preferredToolId = effectiveChatPreferredToolId({
      requestedToolId: toolConfiguration.preferredToolId,
      agent: activeAgent,
      plugins: memberPlugins ?? [],
      incognito: incognitoEnabled,
    });
    const { isLoading: isLoadingProjects } = useProjects();
    const activeProject = useActiveProject();

    // A file isn't queryable until processing completes, so gate send on it.
    const hasPendingFiles = useMemo(
      () => currentMessageFiles.some((file) => isFilePending(file.status)),
      [currentMessageFiles]
    );

    // The composer sends a normal message; tests read this as idle.
    const acceptsSend =
      chatState === "input" && !disabled && !isClassifying && !hasPendingFiles;

    // Text typed while Onyx responds becomes pending input.
    const hasPendingInput = responding && Boolean(message.trim());
    const canSubmitPending =
      queue.enabled &&
      !queue.busy &&
      responding &&
      !isSearchMode &&
      !queue.needsResponseSelection &&
      // A queued message keeps one model; a comparison has none to keep.
      !isMultiModelActive &&
      currentMessageFiles.length === 0;

    const pendingMessageHint = t(
      incognitoEnabled
        ? "appInputBar.pendingMessages.incognitoHint"
        : !queue.enabled
          ? "appInputBar.pendingMessages.waitHint"
          : currentMessageFiles.length > 0
            ? "appInputBar.pendingMessages.attachmentsHint"
            : queue.needsResponseSelection
              ? "appInputBar.pendingMessages.chooseResponseHint"
              : isMultiModelActive
                ? "appInputBar.pendingMessages.multiModelHint"
                : sendDelivery === "interrupt"
                  ? "appInputBar.pendingMessages.interruptHint"
                  : "appInputBar.pendingMessages.sendHint"
    );

    // Returned text goes before any newer text, in the composer or, for a chat
    // that is no longer open, in that chat's own draft.
    function returnText(sessionId: string, returned: ComposedMessage) {
      const isOpen =
        mountedRef.current &&
        useChatSessionStore.getState().currentSessionId === sessionId;
      const key = draftKey("chat", sessionId);
      const newer = isOpen
        ? composedRef.current
        : toChatDraft(readDraft<StoredChatDraft>(key) ?? "");
      const combined: ComposedMessage = newer.message.trim()
        ? {
            message: `${returned.message}\n\n${newer.message}`,
            // Restoring the draft rebuilds one tile per mention, so repeats
            // here are harmless.
            mentions: [...returned.mentions, ...newer.mentions],
          }
        : returned;
      if (!isOpen) {
        writeDraft(key, combined, isChatDraftEmpty);
        return;
      }
      // The composer saves its draft after a delay that a chat switch cancels;
      // the server no longer holds this text, so it is saved at once.
      writeDraft(chatDraftStorageKey, combined, isChatDraftEmpty);
      setMessage(combined.message, combined.mentions);
      setCursorToEnd();
    }

    async function submitPendingMessage(
      delivery: PendingChatMessage["delivery"]
    ) {
      if (!canSubmitPending || !hasPendingInput || disabled || isClassifying)
        return;
      const sessionId = currentSessionId;
      if (sessionId === null) return;
      if (delivery === "interrupt") stopTTS({ manual: true });
      clearMessage();
      clearChatDraft();
      if (
        await queue.submit(
          { ...composed, message: composed.message.trim() },
          // A send into the running response applies no mentions, so a
          // message with mentions waits for its own turn.
          delivery === "send" && composed.mentions.length > 0
            ? "queue"
            : delivery,
          {
            deepResearch: deepResearchEnabled && showDeepResearch,
            // The turn uses the model the picker shows, as a normal send does.
            llmOverride: {
              model_provider: llmManager.currentLlm.name,
              model_version: llmManager.currentLlm.modelName,
              model_configuration_id:
                llmManager.currentLlm.modelConfigurationId ?? null,
              temperature: llmManager.hasTemperatureOverride
                ? llmManager.temperature
                : undefined,
            },
          }
        )
      )
        return;
      returnText(sessionId, composed);
    }

    async function withdrawPendingMessage(index: number, edit: boolean) {
      const pending = queue.messages[index];
      const sessionId = currentSessionId;
      if (
        !pending ||
        sessionId === null ||
        (edit && composedRef.current.message.trim())
      )
        return;
      if (edit) setEditWithdrawalSession(sessionId);
      const withdrawn = await queue.withdraw(pending.id);
      if (edit)
        setEditWithdrawalSession((current) =>
          current === sessionId ? null : current
        );
      if (edit && withdrawn)
        returnText(sessionId, {
          message: withdrawn.message,
          mentions: withdrawn.mentions,
        });
    }

    function interruptWithQueuedMessage(index: number) {
      const pending = queue.messages[index];
      if (!pending || disabled) return;
      stopTTS({ manual: true });
      void queue.interrupt(pending.id);
    }

    const queueNav = useQueuedMessageNavigation({
      messages: queuedMessages,
      inputIsEmpty: !message,
      onRemove: (index) => void withdrawPendingMessage(index, false),
      onEdit: (index) => void withdrawPendingMessage(index, true),
      onSendNow: interruptWithQueuedMessage,
    });

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
    // The list itself belongs to ToolsPopover, which reads it directly; only
    // the loading flag is wanted here, to hold the controls back.
    const { isLoading: sourcesLoading } = useAvailableSources();

    // Bottom controls are hidden until all data is loaded
    const controlsLoading =
      sourcesLoading || !activeAgent || llmManager.isLoadingProviders;
    const [showPrompts, setShowPrompts] = useState(false);

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
        mentionPicker.onInput(event);
        if (text.startsWith("/")) {
          setShowPrompts(true);
          setPromptFilterQuery(text.slice(1));
        } else {
          hidePrompts();
          setPromptFilterQuery("");
        }
      },
      [handleInput, mentionPicker.onInput, hidePrompts, setPromptFilterQuery]
    );

    const shouldCompactImages = useMemo(() => {
      return currentMessageFiles.length > 1;
    }, [currentMessageFiles]);

    // Check if the agent has search tools available (internal search or web search)
    // AND if deep research is globally enabled in admin settings
    const showDeepResearch = useMemo(() => {
      const deepResearchGloballyEnabled =
        combinedSettingsData?.deep_research_enabled ?? true;

      // Resolved from the chat, not the URL. `projectId` is dropped once a chat
      // opens (`PARAMS_TO_SKIP` in `app/app/services/lib.tsx`), so a project
      // chat carries no project context in its URL — reading the search param
      // hid the toggle on the project page and left it showing in the one place
      // it actually breaks.
      // Loading counts as "unknown", and unknown withholds: an unloaded
      // projects list makes a project chat look like a normal one.
      const isProjectWorkflow = isLoadingProjects || activeProject !== null;

      // TODO(@yuhong): Re-enable Deep Research in Projects workflow once it is fully supported.
      // https://linear.app/onyx-app/issue/ENG-3818/re-enable-deep-research-in-projects
      return (
        !isProjectWorkflow &&
        deepResearchGloballyEnabled &&
        hasSearchToolsAvailable(activeAgent?.tools || [])
      );
    }, [
      activeAgent?.tools,
      combinedSettingsData?.deep_research_enabled,
      activeProject,
      isLoadingProjects,
    ]);

    function handleKeyDownForPromptShortcuts(
      e: React.KeyboardEvent<HTMLDivElement>
    ) {
      if (
        !user?.preferences?.shortcut_enabled ||
        !showPrompts ||
        mentionPickerOpen
      )
        return;

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
          "relative flex justify-between items-center w-full",
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
                tooltip={t("appInputBar.attachFilesButton.tooltip")}
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
            {activeAgent && (
              // Keyed, so switching agents starts clean rather than carrying
              // the previous agent's open panel and search term across.
              <ToolsPopover
                key={activeAgent.id}
                agent={activeAgent}
                toolConfiguration={toolConfiguration}
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
                    : t("appInputBar.tabReadingButton.readingLabel")
                  : t("appInputBar.tabReadingButton.readLabel")}
              </SelectButton>
            ) : (
              showDeepResearch && (
                <SelectButton
                  disabled={disabled || isMultiModelActive || incognitoEnabled}
                  variant="select-light"
                  icon={SvgHourglass}
                  onClick={toggleDeepResearch}
                  state={deepResearchEnabled ? "selected" : "empty"}
                  foldable={!deepResearchEnabled}
                  tooltip={
                    incognitoEnabled
                      ? t("appInputBar.deepResearchButton.incognitoTooltip")
                      : isMultiModelActive
                        ? t("appInputBar.deepResearchButton.disabledTooltip")
                        : undefined
                  }
                >
                  {t("appInputBar.deepResearchButton.label")}
                </SelectButton>
              )
            )}

            {!isSearchMode && !controlsLoading && activeAgent && (
              <MCPConnectionPrompt
                key={`mcp-auth-${activeAgent.id}`}
                isStreaming={chatState === "streaming"}
                agent={activeAgent}
                toolConfiguration={toolConfiguration}
                disabled={disabled}
                onConnectionsClosed={() => inputRef.current?.focus()}
              />
            )}

            {(() => {
              if (!activeAgent || preferredToolId === null) return null;
              const tool = activeAgent.tools.find(
                (tool) => tool.id === preferredToolId
              );
              if (!tool) return null;
              return (
                <Disabled disabled={disabled}>
                  <SelectButton
                    variant="select-light"
                    icon={getIconForAction(tool)}
                    onClick={clearPreferredTool}
                    state="selected"
                  >
                    {tool.display_name}
                  </SelectButton>
                </Disabled>
              );
            })()}
          </div>
        </div>

        {/* One row, so the activity and the hint cannot overlap. */}
        {((queue.hasActiveSubagents && !isSearchMode) || hasPendingInput) && (
          <Section
            flexDirection="row"
            justifyContent="end"
            width="auto"
            height="fit"
            gap={1}
            padding={1}
            className="min-w-0 flex-1"
          >
            {queue.hasActiveSubagents && !isSearchMode && (
              <Section
                flexDirection="row"
                justifyContent="start"
                width="auto"
                height="fit"
                gap={1}
                data-testid="subagent-activity"
                className="shrink-0"
              >
                {/* The live region holds only the status text, not the Stop control. */}
                <Section
                  flexDirection="row"
                  justifyContent="start"
                  width="auto"
                  height="fit"
                  gap={1}
                  role="status"
                >
                  <span
                    aria-hidden
                    className="size-1.5 shrink-0 rounded-full bg-status-info-05 motion-safe:animate-pulse"
                  />
                  <Text font="secondary-body" color="text-03" maxLines={1}>
                    {t("appInputBar.subagentsWorking")}
                  </Text>
                </Section>
                <Button
                  icon={SvgStop}
                  prominence="tertiary"
                  size="xs"
                  aria-label={t("appInputBar.stopSubagentsButton.label")}
                  tooltip={t("appInputBar.stopSubagentsButton.label")}
                  onClick={() => void queue.stopSubagents()}
                />
              </Section>
            )}
            {hasPendingInput && (
              <Section
                flexDirection="row"
                justifyContent="end"
                width="auto"
                height="fit"
                gap={1}
                data-testid="pending-message-hint"
                role="note"
                aria-label={
                  !canSubmitPending
                    ? pendingMessageHint
                    : sendDelivery === "interrupt"
                      ? t("appInputBar.pendingMessages.interruptKeyboardHint")
                      : t("appInputBar.pendingMessages.keyboardHint")
                }
                className="min-w-0"
              >
                {canSubmitPending ? (
                  <>
                    <Keycap>↵</Keycap>
                    <Text font="secondary-body" color="text-03" maxLines={1}>
                      {t(
                        sendDelivery === "interrupt"
                          ? "appInputBar.pendingMessages.interruptLabel"
                          : "appInputBar.pendingMessages.sendLabel"
                      )}
                    </Text>
                    <Keycap>
                      {isMac ? "⌘" : t("appInputBar.pendingMessages.ctrlKey")}
                    </Keycap>
                    <Keycap>↵</Keycap>
                    <Text font="secondary-body" color="text-03" maxLines={1}>
                      {t("appInputBar.pendingMessages.queueLabel")}
                    </Text>
                  </>
                ) : (
                  <Text
                    font="secondary-body"
                    color="text-03"
                    maxLines={1}
                    overflowTooltip
                  >
                    {pendingMessageHint}
                  </Text>
                )}
              </Section>
            )}
          </Section>
        )}

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
                  submitMessage({ message: text, mentions: [] });
                }}
                onMuteChange={setIsMuted}
                setMutedRef={setMutedRef}
                onAudioLevel={setAudioLevel}
              />
            ) : (
              <Button
                disabled
                icon={SvgMicrophone}
                aria-label={t("appInputBar.voiceSetupButton.ariaLabel")}
                prominence="tertiary"
                tooltip={t("appInputBar.voiceSetupButton.tooltip")}
              />
            ))}

          {canStopGeneration && hasPendingInput && (
            <Button
              prominence="tertiary"
              icon={SvgStop}
              aria-label={t("baseInputBar.stopButton.ariaLabel")}
              tooltip={t("baseInputBar.stopButton.ariaLabel")}
              onClick={() => {
                stopTTS({ manual: true });
                stopGenerating();
              }}
            />
          )}
          <Button
            disabled={
              chatState === "cancelling" ||
              (isCheckingCompletion && chatState === "unconfirmed") ||
              ((chatState === "input" || responding) &&
                !canStopGeneration &&
                !isVoicePlaybackControllable &&
                !message) ||
              hasPendingFiles ||
              isClassifying ||
              (hasPendingInput && !canSubmitPending)
            }
            tooltip={
              chatState === "cancelling"
                ? t("appInputBar.sendButton.stoppingLabel")
                : hasPendingFiles
                  ? t("appInputBar.sendButton.processingFilesTooltip")
                  : hasPendingInput
                    ? pendingMessageHint
                    : undefined
            }
            aria-label={
              !hasPendingInput
                ? undefined
                : sendDelivery === "interrupt"
                  ? t("appInputBar.pendingMessages.interruptLabel")
                  : t("baseInputBar.sendButton.sendLabel")
            }
            id="onyx-chat-input-send-button"
            icon={
              isCheckingCompletion && chatState === "unconfirmed"
                ? IconLoader
                : chatState === "unconfirmed"
                  ? SvgRefreshCw
                  : isClassifying || chatState === "cancelling"
                    ? IconLoader
                    : chatState !== "input" && message.trim()
                      ? SvgArrowUp
                      : canStopGeneration || isVoicePlaybackControllable
                        ? SvgStop
                        : SvgArrowUp
            }
            onClick={() => {
              if (chatState === "unconfirmed") {
                const store = useChatSessionStore.getState();
                const sessionId = store.currentSessionId;
                const session = sessionId
                  ? store.sessions.get(sessionId)
                  : undefined;
                if (!sessionId || !session || isCheckingCompletion) return;
                setCheckingSessions((pending) =>
                  new Set(pending).add(sessionId)
                );
                void settleChatSession({
                  sessionId,
                  controller: session.abortController,
                  errorMessage: tReadiness("checkFailed"),
                  mode: "recovery",
                }).finally(() =>
                  setCheckingSessions((pending) => {
                    const remaining = new Set(pending);
                    remaining.delete(sessionId);
                    return remaining;
                  })
                );
                return;
              }
              const canSubmitNormally = chatState === "input";
              if (!canSubmitNormally && message.trim()) {
                void submitPendingMessage(sendDelivery);
              } else if (canStopGeneration) {
                stopTTS({ manual: true });
                stopGenerating();
              } else if (isVoicePlaybackControllable) {
                stopTTS({ manual: true });
              } else if (message) {
                submitMessage(composed);
              }
            }}
          >
            {chatState === "cancelling"
              ? t("appInputBar.sendButton.stoppingLabel")
              : chatState === "unconfirmed"
                ? t("appInputBar.sendButton.reloadLabel")
                : undefined}
          </Button>
        </div>
      </div>
    );

    return (
      <>
        <QueuedMessageBar
          messages={queuedMessages}
          highlightedId={queueNav.highlightedId}
          onDiscard={(index) => void withdrawPendingMessage(index, false)}
          onEdit={(index) => void withdrawPendingMessage(index, true)}
          onSendNow={interruptWithQueuedMessage}
          disabled={queue.busy || disabled}
          canEdit={!message.trim()}
        />
        {queue.error && (
          <Section padding={1} width="full" height="fit">
            <Text font="secondary-body" color="text-03">
              {queue.error}
            </Text>
          </Section>
        )}
        <Disabled disabled={disabled} allowClick>
          <div
            ref={containerRef}
            id="onyx-chat-input"
            data-chat-state={chatState}
            data-accepts-send={acceptsSend}
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
              <div className="absolute bottom-full mb-1 start-1 z-10">
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
              <div className="absolute bottom-full mb-1 start-1 end-1 z-10">
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
                    onFileClick={handleFileClick}
                    compactImages={shouldCompactImages}
                  />
                ))}
              </div>
            </div>

            <div className="flex flex-row items-center w-full">
              <Popover
                open={
                  user?.preferences?.shortcut_enabled &&
                  showPrompts &&
                  !mentionPickerOpen
                }
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
                      aria-label={t("appInputBar.input.ariaLabel")}
                      contentEditable={!disabled && !withdrawingForEdit}
                      // Direction follows what the user types. While empty
                      // it follows the placeholder so its punctuation sits
                      // on the correct side in every locale.
                      dir={
                        message
                          ? "auto"
                          : (firstStrongTextDir(activePlaceholder) ?? "auto")
                      }
                      suppressContentEditableWarning
                      onPaste={handlePaste}
                      onCopy={handleCopy}
                      onCut={handleCut}
                      onMouseDown={handleTileMouseDown}
                      onClick={handleTileClick}
                      onBlur={() => queueNav.setHighlightedId(null)}
                      onKeyDownCapture={handleKeyDownForPromptShortcuts}
                      onInput={handleContentEditableInput}
                      onKeyUp={mentionPicker.onSelectionChange}
                      onMouseUp={mentionPicker.onSelectionChange}
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
                      aria-placeholder={t("appInputBar.input.placeholder")}
                      data-placeholder={activePlaceholder}
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
                          !mentionPickerOpen &&
                          !event.shiftKey &&
                          !event.nativeEvent.isComposing
                        ) {
                          event.preventDefault();
                          if (chatState === "input") {
                            if (message && acceptsSend) {
                              submitMessage(composed);
                            }
                          } else if (canSubmitPending) {
                            void submitPendingMessage(
                              event.ctrlKey || event.metaKey
                                ? "queue"
                                : sendDelivery
                            );
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
                  width={70}
                >
                  <Popover.Menu>
                    {[
                      ...sortedFilteredPrompts.map((prompt, index) => (
                        <LineItemButton
                          font="main-ui-action"
                          rounding={2}
                          key={prompt.id}
                          state={
                            tabbingIconIndex === index ? "selected" : "empty"
                          }
                          selectVariant={
                            tabbingIconIndex === index
                              ? "select-heavy"
                              : "select-light"
                          }
                          description={prompt.content?.trim()}
                          onClick={() => updateInputPrompt(prompt)}
                          title={prompt.prompt}
                        />
                      )),
                      sortedFilteredPrompts.length > 0 ? null : undefined,
                      <LineItemButton
                        font="main-ui-action"
                        rounding={2}
                        key="create-new"
                        {...navigation.linkTo("/app/settings/chat-preferences")}
                        icon={SvgPlus}
                        state={
                          tabbingIconIndex === sortedFilteredPrompts.length
                            ? "selected"
                            : "empty"
                        }
                        selectVariant={
                          tabbingIconIndex === sortedFilteredPrompts.length
                            ? "select-heavy"
                            : "select-light"
                        }
                        title={t("appInputBar.createPromptItem.title")}
                      />,
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
                    disabled={
                      !message ||
                      isClassifying ||
                      hasPendingFiles ||
                      chatState === "cancelling" ||
                      chatState === "unconfirmed"
                    }
                    id="onyx-chat-input-send-button"
                    icon={isClassifying ? IconLoader : SvgSearch}
                    onClick={() => {
                      if (chatState == "streaming") {
                        stopGenerating();
                      } else if (message) {
                        submitMessage(composed);
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
              <div className="absolute top-full mt-1 start-1 end-1 z-10">
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
            <EntryPickerPopover
              open={mentionPickerOpen}
              anchorRect={mentionPicker.anchorRect}
              query={mentionPicker.query}
              sections={mentionSections}
              onSelect={mentionPicker.onSelect}
              onClose={mentionPicker.onClose}
              trigger={MENTION_TRIGGER}
            />
          </div>
        </Disabled>
        {/* Stays for the whole session: the warning is most relevant
            once the user is actually chatting. */}
        {incognitoEnabled && (
          <Section
            flexDirection="column"
            alignItems="center"
            height="fit"
            gap={0.125}
            className="mt-3 text-center"
          >
            <Text font="secondary-body" color="text-02">
              {t("appInputBar.incognitoNotice.text")}
            </Text>
            <Text font="secondary-body" color="text-02">
              {t("appInputBar.incognitoPolicyNotice.text")}
            </Text>
          </Section>
        )}
      </>
    );
  }
);
AppInputBar.displayName = "AppInputBar";

export default AppInputBar;
