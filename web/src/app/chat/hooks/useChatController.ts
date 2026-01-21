"use client";

import {
  buildChatUrl,
  nameChatSession,
  updateLlmOverrideForChatSession,
} from "../services/lib";

import { StreamStopInfo } from "@/lib/search/interfaces";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Route } from "next";
import { stopChatSession } from "../chat_search/utils";
import {
  getLastSuccessfulMessageId,
  getLatestMessageChain,
  MessageTreeState,
  upsertMessages,
  SYSTEM_NODE_ID,
  buildImmediateMessages,
  buildEmptyMessage,
} from "../services/messageTree";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { SEARCH_PARAM_NAMES } from "../services/searchParams";
import { SEARCH_TOOL_ID } from "../components/tools/constants";
import { OnyxDocument } from "@/lib/search/interfaces";
import { FilterManager, LlmDescriptor, LlmManager } from "@/lib/hooks";
import {
  BackendMessage,
  ChatFileType,
  CitationMap,
  FileChatDisplay,
  FileDescriptor,
  Message,
  MessageResponseIDInfo,
  RegenerationState,
  RetrievalType,
  StreamingError,
  ToolCallMetadata,
  UserKnowledgeFilePacket,
} from "../interfaces";
import { StreamStopReason } from "@/lib/search/interfaces";
import { createChatSession } from "../services/lib";
import {
  getFinalLLM,
  modelSupportsImageInput,
  structureValue,
} from "@/lib/llm/utils";
import {
  CurrentMessageFIFO,
  updateCurrentMessageFIFO,
} from "../services/currentMessageFIFO";
import { buildFilters } from "@/lib/search/utils";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import {
  ReadonlyURLSearchParams,
  usePathname,
  useRouter,
  useSearchParams,
} from "next/navigation";
import { usePostHog } from "posthog-js/react";
import { getExtensionContext } from "@/lib/extension/utils";
import useChatSessions from "@/hooks/useChatSessions";
import { usePinnedAgents } from "@/hooks/useAgents";
import {
  useChatSessionStore,
  useCurrentMessageTree,
  useCurrentChatState,
  useCurrentMessageHistory,
} from "../stores/useChatSessionStore";
import { Packet, MessageStart, PacketType } from "../services/streamingModels";
import { useAssistantPreferences } from "@/app/chat/hooks/useAssistantPreferences";
import { useForcedTools } from "@/lib/hooks/useForcedTools";
import { ProjectFile, useProjectsContext } from "../projects/ProjectsContext";
import { useAppParams } from "@/hooks/appNavigation";
import { projectFilesToFileDescriptors } from "../services/fileUtils";

const SYSTEM_MESSAGE_ID = -3;

export interface OnSubmitProps {
  message: string;
  //from chat input bar
  currentMessageFiles: ProjectFile[];
  // from the chat bar???

  deepResearch: boolean;

  // optional params
  messageIdToResend?: number;
  queryOverride?: string;
  forceSearch?: boolean;
  isSeededChat?: boolean;
  modelOverride?: LlmDescriptor;
  regenerationRequest?: RegenerationRequest | null;
}

interface RegenerationRequest {
  messageId: number;
  parentMessage: Message;
  forceSearch?: boolean;
}

interface UseChatControllerProps {
  filterManager: FilterManager;
  llmManager: LlmManager;
  liveAssistant: MinimalPersonaSnapshot | undefined;
  availableAssistants: MinimalPersonaSnapshot[];
  existingChatSessionId: string | null;
  selectedDocuments: OnyxDocument[];
  searchParams: ReadonlyURLSearchParams;
  setPopup: (popup: PopupSpec) => void;
  resetInputBar: () => void;
  setSelectedAssistantFromId: (assistantId: number | null) => void;
}

export function useChatController({
  filterManager,
  llmManager,
  availableAssistants,
  liveAssistant,
  existingChatSessionId,
  selectedDocuments,
  setPopup,
  resetInputBar,
  setSelectedAssistantFromId,
}: UseChatControllerProps) {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const params = useAppParams();
  const { refreshChatSessions, addPendingChatSession } = useChatSessions();
  const { pinnedAgents, togglePinnedAgent } = usePinnedAgents();
  const { assistantPreferences } = useAssistantPreferences();
  const { forcedToolIds } = useForcedTools();
  const { fetchProjects, setCurrentMessageFiles, beginUpload } =
    useProjectsContext();
  const posthog = usePostHog();

  // Use selectors to access only the specific fields we need
  const currentSessionId = useChatSessionStore(
    (state) => state.currentSessionId
  );
  const sessions = useChatSessionStore((state) => state.sessions);

  // Store actions - these don't cause re-renders
  const updateChatStateAction = useChatSessionStore(
    (state) => state.updateChatState
  );
  const updateRegenerationStateAction = useChatSessionStore(
    (state) => state.updateRegenerationState
  );
  const updateCanContinueAction = useChatSessionStore(
    (state) => state.updateCanContinue
  );
  const createSession = useChatSessionStore((state) => state.createSession);
  const setCurrentSession = useChatSessionStore(
    (state) => state.setCurrentSession
  );
  const updateSessionMessageTree = useChatSessionStore(
    (state) => state.updateSessionMessageTree
  );
  const updateSubmittedMessage = useChatSessionStore(
    (state) => state.updateSubmittedMessage
  );
  const updateSelectedNodeForDocDisplay = useChatSessionStore(
    (state) => state.updateSelectedNodeForDocDisplay
  );
  const setUncaughtError = useChatSessionStore(
    (state) => state.setUncaughtError
  );
  const setLoadingError = useChatSessionStore((state) => state.setLoadingError);
  const setAbortController = useChatSessionStore(
    (state) => state.setAbortController
  );
  const setIsReady = useChatSessionStore((state) => state.setIsReady);

  // Use custom hooks for accessing store data
  const currentMessageTree = useCurrentMessageTree();
  const currentMessageHistory = useCurrentMessageHistory();
  const currentChatState = useCurrentChatState();

  const navigatingAway = useRef(false);

  // Local state that doesn't need to be in the store
  const [_maxTokens, setMaxTokens] = useState<number>(4096);

  // Sync store state changes
  useEffect(() => {
    if (currentSessionId) {
      // Keep track of current session ID for internal use
    }
  }, [currentSessionId]);

  const getCurrentSessionId = (): string => {
    return currentSessionId || existingChatSessionId || "";
  };

  const updateRegenerationState = (
    newState: RegenerationState | null,
    sessionId?: string | null
  ) => {
    const targetSessionId = sessionId || getCurrentSessionId();
    if (targetSessionId) {
      updateRegenerationStateAction(targetSessionId, newState);
    }
  };

  const resetRegenerationState = (sessionId?: string | null) => {
    updateRegenerationState(null, sessionId);
  };

  const updateCanContinue = (newState: boolean, sessionId?: string | null) => {
    const targetSessionId = sessionId || getCurrentSessionId();
    if (targetSessionId) {
      updateCanContinueAction(targetSessionId, newState);
    }
  };

  const updateStatesWithNewSessionId = (newSessionId: string) => {
    // Create new session in store if it doesn't exist
    const existingSession = sessions.get(newSessionId);
    if (!existingSession) {
      createSession(newSessionId);
    }

    // Set as current session
    setCurrentSession(newSessionId);
  };

  const handleNewSessionNavigation = (chatSessionId: string) => {
    // Build URL with skip-reload parameter
    const newUrl = buildChatUrl(
      searchParams,
      chatSessionId,
      null,
      false,
      true // skipReload
    );

    // Navigate immediately if still on chat page
    // For NRF pages (/chat/nrf, /chat/nrf/side-panel), don't navigate immediately
    // Let the streaming complete inline, then the user can continue chatting there
    const isOnChatPage = pathname === "/chat";

    if (isOnChatPage && !navigatingAway.current) {
      router.push(newUrl as Route, { scroll: false });
    }

    // Refresh sidebar - the chat was already optimistically added via addPendingChatSession
    // so it will show as "New Chat". This refresh ensures we get the latest server state
    // and will be called again after naming completes.
    refreshChatSessions();
    fetchProjects();
  };

  const handleNewSessionNaming = async (chatSessionId: string) => {
    // Wait 200ms before naming (gives backend time to process)
    // There is some delay here since we might get a "finished" response from the backend
    // before the ChatSession is written to the database.
    // TODO: remove this delay once we have a way to know when the ChatSession
    // is written to the database.
    await new Promise((resolve) => setTimeout(resolve, 200));

    try {
      // Name chat based on AI response
      const response = await nameChatSession(chatSessionId);

      if (!response.ok) {
        console.error("Failed to name chat session, status:", response.status);
        // Still refresh to show the unnamed chat in sidebar
        refreshChatSessions();
        fetchProjects();
        return;
      }
    } catch (error) {
      console.error("Failed to name chat session:", error);
    } finally {
      // Refresh sidebar to show new name
      await refreshChatSessions();
      await fetchProjects();
    }
  };

  const upsertToCompleteMessageTree = ({
    messages,
    chatSessionId,
    completeMessageTreeOverride,
    makeLatestChildMessage = false,
  }: {
    messages: Message[];
    chatSessionId: string;
    // if calling this function repeatedly with short delay, stay may not update in time
    // and result in weird behavipr
    completeMessageTreeOverride?: MessageTreeState | null;
    oldIds?: number[] | null;
    makeLatestChildMessage?: boolean;
  }) => {
    let currentMessageTreeToUse =
      completeMessageTreeOverride ||
      (chatSessionId !== undefined &&
        sessions.get(chatSessionId)?.messageTree) ||
      currentMessageTree ||
      new Map<number, Message>();

    const newCompleteMessageTree = upsertMessages(
      currentMessageTreeToUse,
      messages,
      makeLatestChildMessage
    );

    updateSessionMessageTree(chatSessionId, newCompleteMessageTree);

    return newCompleteMessageTree;
  };

  const stopGenerating = useCallback(async () => {
    const currentSession = getCurrentSessionId();
    const lastMessage = currentMessageHistory[currentMessageHistory.length - 1];

    // Call the backend stop endpoint to set the Redis fence
    // This signals the backend to stop processing as soon as possible
    // The backend will emit a STOP packet when it detects the fence
    try {
      await stopChatSession(currentSession);
    } catch (error) {
      console.error("Failed to stop chat session:", error);
      // Continue with UI cleanup even if backend call fails
    }

    // Clean up incomplete tool calls for immediate UI feedback
    if (
      lastMessage &&
      lastMessage.type === "assistant" &&
      lastMessage.toolCall &&
      lastMessage.toolCall.tool_result === undefined
    ) {
      const newMessageTree = new Map(currentMessageTree);
      const updatedMessage = { ...lastMessage, toolCall: null };
      newMessageTree.set(lastMessage.nodeId, updatedMessage);
      updateSessionMessageTree(currentSession, newMessageTree);
    }

    // Update chat state to input immediately for good UX
    // The stream will close naturally when the backend sends the STOP packet
    updateChatStateAction(currentSession, "input");
  }, [currentMessageHistory, currentMessageTree]);

  const onSubmit = useCallback(
    async ({
      message,
      currentMessageFiles,
      deepResearch,
      messageIdToResend,
      queryOverride,
      forceSearch,
      isSeededChat,
      modelOverride,
      regenerationRequest,
    }: OnSubmitProps) => {
      const projectId = params(SEARCH_PARAM_NAMES.PROJECT_ID);
      {
        const params = new URLSearchParams(searchParams?.toString() || "");
        if (params.has(SEARCH_PARAM_NAMES.PROJECT_ID)) {
          params.delete(SEARCH_PARAM_NAMES.PROJECT_ID);
          const newUrl = params.toString()
            ? `${pathname}?${params.toString()}`
            : pathname;
          router.replace(newUrl as Route, { scroll: false });
        }
      }

      updateSubmittedMessage(getCurrentSessionId(), message);

      navigatingAway.current = false;
      let frozenSessionId = getCurrentSessionId();
      updateCanContinue(false, frozenSessionId);
      setUncaughtError(frozenSessionId, null);
      setLoadingError(frozenSessionId, null);

      // Check if the last message was an error and remove it before proceeding with a new message
      // Ensure this isn't a regeneration or resend, as those operations should preserve the history leading up to the point of regeneration/resend.
      let currentMessageTreeLocal =
        currentMessageTree || new Map<number, Message>();
      let currentHistory = getLatestMessageChain(currentMessageTreeLocal);
      let lastMessage = currentHistory[currentHistory.length - 1];

      if (
        lastMessage &&
        lastMessage.type === "error" &&
        !messageIdToResend &&
        !regenerationRequest
      ) {
        const newMessageTree = new Map(currentMessageTreeLocal);
        const parentNodeId = lastMessage.parentNodeId;

        // Remove the error message itself
        newMessageTree.delete(lastMessage.nodeId);

        // Remove the parent message + update the parent of the parent to no longer
        // link to the parent
        if (parentNodeId !== null && parentNodeId !== undefined) {
          const parentOfError = newMessageTree.get(parentNodeId);
          if (parentOfError) {
            const grandparentNodeId = parentOfError.parentNodeId;
            if (grandparentNodeId !== null && grandparentNodeId !== undefined) {
              const grandparent = newMessageTree.get(grandparentNodeId);
              if (grandparent) {
                // Update grandparent to no longer link to parent
                const updatedGrandparent = {
                  ...grandparent,
                  childrenNodeIds: (grandparent.childrenNodeIds || []).filter(
                    (id: number) => id !== parentNodeId
                  ),
                  latestChildNodeId:
                    grandparent.latestChildNodeId === parentNodeId
                      ? null
                      : grandparent.latestChildNodeId,
                };
                newMessageTree.set(grandparentNodeId, updatedGrandparent);
              }
            }
            // Remove the parent message
            newMessageTree.delete(parentNodeId);
          }
        }
        // Update the state immediately so subsequent logic uses the cleaned map
        updateSessionMessageTree(frozenSessionId, newMessageTree);
        console.log(
          "Removed previous error message ID:",
          lastMessage.messageId
        );

        // update state for the new world (with the error message removed)
        currentHistory = getLatestMessageChain(newMessageTree);
        currentMessageTreeLocal = newMessageTree;
        lastMessage = currentHistory[currentHistory.length - 1];
      }

      if (currentChatState != "input") {
        if (currentChatState == "uploading") {
          setPopup({
            message: "Please wait for the content to upload",
            type: "error",
          });
        } else {
          setPopup({
            message: "Please wait for the response to complete",
            type: "error",
          });
        }

        return;
      }

      // Auto-pin the agent to sidebar when sending a message if not already pinned
      if (liveAssistant) {
        const isAlreadyPinned = pinnedAgents.some(
          (agent) => agent.id === liveAssistant.id
        );
        if (!isAlreadyPinned) {
          togglePinnedAgent(liveAssistant, true).catch((err) => {
            console.error("Failed to auto-pin agent:", err);
          });
        }
      }

      let currChatSessionId: string;
      // Check both the prop and the store's currentSessionId to determine if this is a new session
      // For pages like NRF where existingChatSessionId is always null, we need to check if
      // we already have a session from a previous message
      const isNewSession = existingChatSessionId === null && !currentSessionId;

      const searchParamBasedChatSessionName =
        searchParams?.get(SEARCH_PARAM_NAMES.TITLE) || null;
      // Auto-name only once, after the first assistant response, and only when the chat isn't
      // already explicitly named (e.g. `?title=...`).
      const hadAnyUserMessagesBeforeSubmit = currentHistory.some(
        (m) => m.type === "user"
      );
      if (isNewSession) {
        currChatSessionId = await createChatSession(
          liveAssistant?.id || 0,
          searchParamBasedChatSessionName,
          projectId ? parseInt(projectId) : null
        );

        // Optimistically add the new chat session to the sidebar cache
        // This ensures "New Chat" appears immediately, even before any messages are saved
        addPendingChatSession({
          chatSessionId: currChatSessionId,
          personaId: liveAssistant?.id || 0,
          projectId: projectId ? parseInt(projectId) : null,
        });
      } else {
        // Use the existing session ID from props or from the store
        currChatSessionId =
          existingChatSessionId || (currentSessionId as string);
      }
      frozenSessionId = currChatSessionId;
      // update the selected model for the chat session if one is specified so that
      // it persists across page reloads. Do not `await` here so that the message
      // request can continue and this will just happen in the background.
      // NOTE: only set the model override for the chat session once we send a
      // message with it. If the user switches models and then starts a new
      // chat session, it is unexpected for that model to be used when they
      // return to this session the next day.
      let finalLLM = modelOverride || llmManager.currentLlm;
      updateLlmOverrideForChatSession(
        currChatSessionId,
        structureValue(
          finalLLM.name || "",
          finalLLM.provider || "",
          finalLLM.modelName || ""
        )
      );

      // mark the session as the current session
      updateStatesWithNewSessionId(currChatSessionId);

      // Navigate immediately for new sessions (before streaming starts)
      if (isNewSession) {
        handleNewSessionNavigation(currChatSessionId);
      }

      const shouldAutoNameChatSessionAfterResponse =
        !searchParamBasedChatSessionName &&
        !hadAnyUserMessagesBeforeSubmit &&
        !sessions.get(currChatSessionId)?.description;

      // set the ability to cancel the request
      const controller = new AbortController();
      setAbortController(currChatSessionId, controller);

      const messageToResend = currentHistory.find(
        (message) => message.messageId === messageIdToResend
      );
      if (messageIdToResend && regenerationRequest) {
        updateRegenerationState(
          { regenerating: true, finalMessageIndex: messageIdToResend + 1 },
          frozenSessionId
        );
      }
      const messageToResendParent =
        messageToResend?.parentNodeId !== null &&
        messageToResend?.parentNodeId !== undefined
          ? currentMessageTreeLocal.get(messageToResend.parentNodeId)
          : null;
      const messageToResendIndex = messageToResend
        ? currentHistory.indexOf(messageToResend)
        : null;

      if (!messageToResend && messageIdToResend !== undefined) {
        setPopup({
          message:
            "Failed to re-send message - please refresh the page and try again.",
          type: "error",
        });
        resetRegenerationState(frozenSessionId);
        updateChatStateAction(frozenSessionId, "input");
        return;
      }

      // When editing (messageIdToResend exists but no regenerationRequest), use the new message
      // When regenerating (regenerationRequest exists), use the original message
      let currMessage = regenerationRequest
        ? messageToResend?.message || message
        : message;

      updateChatStateAction(frozenSessionId, "loading");

      // find the parent
      const currMessageHistory =
        messageToResendIndex !== null
          ? currentHistory.slice(0, messageToResendIndex)
          : currentHistory;

      let parentMessage =
        messageToResendParent ||
        (currMessageHistory.length > 0
          ? currMessageHistory[currMessageHistory.length - 1]
          : null) ||
        (currentMessageTreeLocal.size === 1
          ? Array.from(currentMessageTreeLocal.values())[0]
          : null);

      // Add user message immediately to the message tree so that the chat
      // immediately reflects the user message
      let initialUserNode: Message;
      let initialAssistantNode: Message;

      if (regenerationRequest) {
        // For regeneration: keep the existing user message, only create new assistant
        initialUserNode = regenerationRequest.parentMessage;
        initialAssistantNode = buildEmptyMessage({
          messageType: "assistant",
          parentNodeId: initialUserNode.nodeId,
          nodeIdOffset: 1,
        });
      } else {
        // For new messages or editing: create/update user message and assistant
        const parentNodeIdForMessage = messageToResend
          ? messageToResend.parentNodeId || SYSTEM_NODE_ID
          : parentMessage?.nodeId || SYSTEM_NODE_ID;
        const result = buildImmediateMessages(
          parentNodeIdForMessage,
          currMessage,
          projectFilesToFileDescriptors(currentMessageFiles),
          messageToResend
        );
        initialUserNode = result.initialUserNode;
        initialAssistantNode = result.initialAssistantNode;
      }

      // make messages appear + clear input bar
      const messagesToUpsert = regenerationRequest
        ? [initialAssistantNode] // Only upsert the new assistant for regeneration
        : [initialUserNode, initialAssistantNode]; // Upsert both for normal/edit flow
      currentMessageTreeLocal = upsertToCompleteMessageTree({
        messages: messagesToUpsert,
        completeMessageTreeOverride: currentMessageTreeLocal,
        chatSessionId: frozenSessionId,
      });
      resetInputBar();

      let answer = "";

      const stopReason: StreamStopReason | null = null;
      let query: string | null = null;
      let retrievalType: RetrievalType =
        selectedDocuments.length > 0
          ? RetrievalType.SelectedDocs
          : RetrievalType.None;
      let documents: OnyxDocument[] = selectedDocuments;
      let citations: CitationMap | null = null;
      let aiMessageImages: FileDescriptor[] | null = null;
      let error: string | null = null;
      let stackTrace: string | null = null;
      let errorCode: string | null = null;
      let isRetryable: boolean = true;
      let errorDetails: Record<string, any> | null = null;

      let finalMessage: BackendMessage | null = null;
      let toolCall: ToolCallMetadata | null = null;
      let files = projectFilesToFileDescriptors(currentMessageFiles);
      let packets: Packet[] = [];

      let newUserMessageId: number | null = null;
      let newAssistantMessageId: number | null = null;

      try {
        const lastSuccessfulMessageId = getLastSuccessfulMessageId(
          currentMessageTreeLocal
        );
        const disabledToolIds = liveAssistant
          ? assistantPreferences?.[liveAssistant?.id]?.disabled_tool_ids
          : undefined;

        // Find the search tool's numeric ID for forceSearch
        const searchToolNumericId = liveAssistant?.tools.find(
          (tool) => tool.in_code_tool_id === SEARCH_TOOL_ID
        )?.id;

        // Determine the forced tool ID:
        // 1. If forceSearch is true, use the search tool's numeric ID
        // 2. Otherwise, use the first forced tool ID from the forcedToolIds array
        const effectiveForcedToolId = forceSearch
          ? searchToolNumericId ?? null
          : forcedToolIds.length > 0
            ? forcedToolIds[0]
            : null;

        // Determine origin for telemetry tracking (also used for frontend PostHog tracking below)
        const { isExtension, context: extensionContext } =
          getExtensionContext();
        const messageOrigin = isExtension ? "chrome_extension" : "webapp";

        const stack = new CurrentMessageFIFO();
        updateCurrentMessageFIFO(stack, {
          signal: controller.signal,
          message: currMessage,
          fileDescriptors: projectFilesToFileDescriptors(currentMessageFiles),
          parentMessageId: (() => {
            const parentId =
              regenerationRequest?.parentMessage.messageId ||
              messageToResendParent?.messageId ||
              lastSuccessfulMessageId;
            // Don't send SYSTEM_MESSAGE_ID (-3) as parent, use null instead
            // The backend expects null for "the first message in the chat"
            return parentId === SYSTEM_MESSAGE_ID ? null : parentId;
          })(),
          chatSessionId: currChatSessionId,
          filters: buildFilters(
            filterManager.selectedSources,
            filterManager.selectedDocumentSets,
            filterManager.timeRange,
            filterManager.selectedTags
          ),
          modelProvider:
            modelOverride?.name || llmManager.currentLlm.name || undefined,
          modelVersion:
            modelOverride?.modelName ||
            llmManager.currentLlm.modelName ||
            searchParams?.get(SEARCH_PARAM_NAMES.MODEL_VERSION) ||
            undefined,
          temperature: llmManager.temperature || undefined,
          deepResearch,
          enabledToolIds:
            disabledToolIds && liveAssistant
              ? liveAssistant.tools
                  .filter((tool) => !disabledToolIds?.includes(tool.id))
                  .map((tool) => tool.id)
              : undefined,
          forcedToolId: effectiveForcedToolId,
          origin: messageOrigin,
        });

        const delay = (ms: number) => {
          return new Promise((resolve) => setTimeout(resolve, ms));
        };

        await delay(50);
        while (!stack.isComplete || !stack.isEmpty()) {
          if (stack.isEmpty()) {
            await delay(0.5);
          }

          if (!stack.isEmpty() && !controller.signal.aborted) {
            const packet = stack.nextPacket();
            if (!packet) {
              continue;
            }
            console.debug("Packet:", JSON.stringify(packet));

            // We've processed initial packets and are starting to stream content.
            // Transition from 'loading' to 'streaming'.
            updateChatStateAction(frozenSessionId, "streaming");

            if ((packet as MessageResponseIDInfo).user_message_id) {
              newUserMessageId = (packet as MessageResponseIDInfo)
                .user_message_id;

              // Track extension queries in PostHog (reuses isExtension/extensionContext from above)
              if (isExtension && posthog) {
                posthog.capture("extension_chat_query", {
                  extension_context: extensionContext,
                  assistant_id: liveAssistant?.id,
                  has_files: currentMessageFiles.length > 0,
                  deep_research: deepResearch,
                });
              }
            }

            if (
              (packet as MessageResponseIDInfo).reserved_assistant_message_id
            ) {
              newAssistantMessageId = (packet as MessageResponseIDInfo)
                .reserved_assistant_message_id;
            }

            if (Object.hasOwn(packet, "user_files")) {
              const userFiles = (packet as UserKnowledgeFilePacket).user_files;
              // Ensure files are unique by id
              const newUserFiles = userFiles.filter(
                (newFile) =>
                  !files.some((existingFile) => existingFile.id === newFile.id)
              );
              files = files.concat(newUserFiles);
            }

            if (Object.hasOwn(packet, "file_ids")) {
              aiMessageImages = (packet as FileChatDisplay).file_ids.map(
                (fileId) => {
                  return {
                    id: fileId,
                    type: ChatFileType.IMAGE,
                  };
                }
              );
            } else if (
              Object.hasOwn(packet, "error") &&
              (packet as any).error != null
            ) {
              const streamingError = packet as StreamingError;
              error = streamingError.error;
              stackTrace = streamingError.stack_trace || null;
              errorCode = streamingError.error_code || null;
              isRetryable = streamingError.is_retryable ?? true;
              errorDetails = streamingError.details || null;

              setUncaughtError(frozenSessionId, streamingError.error);
              updateChatStateAction(frozenSessionId, "input");
              updateSubmittedMessage(getCurrentSessionId(), "");

              throw new Error(streamingError.error);
            } else if (Object.hasOwn(packet, "message_id")) {
              finalMessage = packet as BackendMessage;
            } else if (Object.hasOwn(packet, "stop_reason")) {
              const stop_reason = (packet as StreamStopInfo).stop_reason;
              if (stop_reason === StreamStopReason.CONTEXT_LENGTH) {
                updateCanContinue(true, frozenSessionId);
              }
            } else if (Object.hasOwn(packet, "obj")) {
              console.debug("Object packet:", JSON.stringify(packet));
              packets.push(packet as Packet);

              // Check if the packet contains document information
              const packetObj = (packet as Packet).obj;

              if (packetObj.type === "citation_info") {
                // Individual citation packet from backend streaming
                const citationInfo = packetObj as {
                  type: "citation_info";
                  citation_number: number;
                  document_id: string;
                };
                // Incrementally build citations map
                citations = {
                  ...(citations || {}),
                  [citationInfo.citation_number]: citationInfo.document_id,
                };
              } else if (packetObj.type === "message_start") {
                const messageStart = packetObj as MessageStart;
                if (messageStart.final_documents) {
                  documents = messageStart.final_documents;
                  updateSelectedNodeForDocDisplay(
                    frozenSessionId,
                    initialAssistantNode.nodeId
                  );
                }
              }
            } else {
              console.warn("Unknown packet:", JSON.stringify(packet));
            }

            // on initial message send, we insert a dummy system message
            // set this as the parent here if no parent is set
            parentMessage =
              parentMessage || currentMessageTreeLocal?.get(SYSTEM_NODE_ID)!;

            currentMessageTreeLocal = upsertToCompleteMessageTree({
              messages: [
                {
                  ...initialUserNode,
                  messageId: newUserMessageId ?? undefined,
                  files: files,
                },
                {
                  ...initialAssistantNode,
                  messageId: newAssistantMessageId ?? undefined,
                  message: error || answer,
                  type: error ? "error" : "assistant",
                  retrievalType,
                  query: finalMessage?.rephrased_query || query,
                  documents: documents,
                  citations: finalMessage?.citations || citations || {},
                  files: finalMessage?.files || aiMessageImages || [],
                  toolCall: finalMessage?.tool_call || toolCall,
                  stackTrace: stackTrace,
                  overridden_model: finalMessage?.overridden_model,
                  stopReason: stopReason,
                  packets: packets,
                },
              ],
              // Pass the latest map state
              completeMessageTreeOverride: currentMessageTreeLocal,
              chatSessionId: frozenSessionId!,
            });
          }
        }
      } catch (e: any) {
        console.log("Error:", e);
        const errorMsg = e.message;
        currentMessageTreeLocal = upsertToCompleteMessageTree({
          messages: [
            {
              nodeId: initialUserNode.nodeId,
              message: currMessage,
              type: "user",
              files: currentMessageFiles.map((file) => ({
                id: file.file_id,
                type: file.chat_file_type,
                name: file.name,
                user_file_id: file.id,
              })),
              toolCall: null,
              parentNodeId: parentMessage?.nodeId || SYSTEM_NODE_ID,
              packets: [],
            },
            {
              nodeId: initialAssistantNode.nodeId,
              message: errorMsg,
              type: "error",
              files: aiMessageImages || [],
              toolCall: null,
              parentNodeId: initialUserNode.nodeId,
              packets: [],
              stackTrace: stackTrace,
              errorCode: errorCode,
              isRetryable: isRetryable,
              errorDetails: errorDetails,
            },
          ],
          completeMessageTreeOverride: currentMessageTreeLocal,
          chatSessionId: frozenSessionId,
        });
      }

      resetRegenerationState(frozenSessionId);
      updateChatStateAction(frozenSessionId, "input");

      // Name the chat now that we have the first AI response (navigation already happened before streaming)
      if (shouldAutoNameChatSessionAfterResponse) {
        handleNewSessionNaming(currChatSessionId);
      }
    },
    [
      // Narrow to stable fields from managers to avoid re-creation
      filterManager.selectedSources,
      filterManager.selectedDocumentSets,
      filterManager.selectedTags,
      filterManager.timeRange,
      llmManager.currentLlm,
      llmManager.temperature,
      // Others that affect logic
      liveAssistant,
      availableAssistants,
      existingChatSessionId,
      selectedDocuments,
      searchParams,
      setPopup,
      resetInputBar,
      setSelectedAssistantFromId,
      updateSelectedNodeForDocDisplay,
      currentMessageTree,
      currentChatState,
      // Ensure latest forced tools are used when submitting
      forcedToolIds,
      // Keep tool preference-derived values fresh
      assistantPreferences,
      fetchProjects,
      // For auto-pinning agents
      pinnedAgents,
      togglePinnedAgent,
    ]
  );

  const handleMessageSpecificFileUpload = useCallback(
    async (acceptedFiles: File[]) => {
      const [_, llmModel] = getFinalLLM(
        llmManager.llmProviders || [],
        liveAssistant || null,
        llmManager.currentLlm
      );
      const llmAcceptsImages = modelSupportsImageInput(
        llmManager.llmProviders || [],
        llmModel
      );

      const imageFiles = acceptedFiles.filter((file) =>
        file.type.startsWith("image/")
      );

      if (imageFiles.length > 0 && !llmAcceptsImages) {
        setPopup({
          type: "error",
          message:
            "The current model does not support image input. Please select a model with Vision support.",
        });
        return;
      }
      updateChatStateAction(getCurrentSessionId(), "uploading");
      const uploadedMessageFiles = await beginUpload(
        Array.from(acceptedFiles),
        null,
        setPopup
      );
      setCurrentMessageFiles((prev) => [...prev, ...uploadedMessageFiles]);
      updateChatStateAction(getCurrentSessionId(), "input");
    },
    [liveAssistant, llmManager, forcedToolIds]
  );

  useEffect(() => {
    return () => {
      // Cleanup which only runs when the component unmounts (i.e. when you navigate away).
      const currentSession = getCurrentSessionId();
      const abortController = sessions.get(currentSession)?.abortController;
      if (abortController) {
        abortController.abort();
        setAbortController(currentSession, new AbortController());
      }
    };
  }, [pathname]);

  // update chosen assistant if we navigate between pages
  useEffect(() => {
    if (currentMessageHistory.length === 0 && existingChatSessionId === null) {
      // Select from available assistants so shared assistants appear.
      setSelectedAssistantFromId(null);
    }
  }, [
    existingChatSessionId,
    availableAssistants,
    currentMessageHistory.length,
  ]);

  useEffect(() => {
    const handleSlackChatRedirect = async () => {
      const slackChatId = searchParams.get("slackChatId");
      if (!slackChatId) return;

      // Set isReady to false before starting retrieval to display loading text
      const currentSessionId = getCurrentSessionId();
      if (currentSessionId) {
        setIsReady(currentSessionId, false);
      }

      try {
        const response = await fetch("/api/chat/seed-chat-session-from-slack", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            chat_session_id: slackChatId,
          }),
        });

        if (!response.ok) {
          throw new Error("Failed to seed chat from Slack");
        }

        const data = await response.json();

        router.push(data.redirect_url);
      } catch (error) {
        console.error("Error seeding chat from Slack:", error);
        setPopup({
          message: "Failed to load chat from Slack",
          type: "error",
        });
      }
    };

    handleSlackChatRedirect();
  }, [searchParams, router]);

  // fetch # of allowed document tokens for the selected Persona
  useEffect(() => {
    if (!liveAssistant?.id) return; // avoid calling with undefined persona id

    async function fetchMaxTokens() {
      const response = await fetch(
        `/api/chat/max-selected-document-tokens?persona_id=${liveAssistant?.id}`
      );
      if (response.ok) {
        const maxTokens = (await response.json()).max_tokens as number;
        setMaxTokens(maxTokens);
      }
    }
    fetchMaxTokens();
  }, [liveAssistant]);

  // check if there's an image file in the message history so that we know
  // which LLMs are available to use
  const imageFileInMessageHistory = useMemo(() => {
    return currentMessageHistory
      .filter((message) => message.type === "user")
      .some((message) =>
        message.files.some((file) => file.type === ChatFileType.IMAGE)
      );
  }, [currentMessageHistory]);

  useEffect(() => {
    llmManager.updateImageFilesPresent(imageFileInMessageHistory);
  }, [imageFileInMessageHistory]);

  // set isReady once component is mounted
  useEffect(() => {
    const currentSessionId = getCurrentSessionId();
    if (currentSessionId) {
      setIsReady(currentSessionId, true);
    }
  }, []);

  return {
    // actions
    onSubmit,
    stopGenerating,
    handleMessageSpecificFileUpload,
  };
}
