"use client";

import {
  buildChatUrl,
  nameChatSession,
  updateLlmOverrideForChatSession,
} from "../services/lib";

import { StreamStopInfo } from "@/lib/search/interfaces";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePostHog } from "posthog-js/react";
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
  ResearchType,
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
import { useChatContext } from "@/refresh-components/contexts/ChatContext";
import Prism from "prismjs";
import {
  useChatSessionStore,
  useCurrentMessageTree,
  useCurrentChatState,
  useCurrentMessageHistory,
} from "../stores/useChatSessionStore";
import {
  Packet,
  CitationDelta,
  MessageStart,
  PacketType,
} from "../services/streamingModels";
import { useAgentsContext } from "@/refresh-components/contexts/AgentsContext";
import { ProjectFile, useProjectsContext } from "../projects/ProjectsContext";
import { CategorizedFiles, UserFileStatus } from "../projects/projectsService";
import { useAppParams } from "@/hooks/appNavigation";
import { projectFilesToFileDescriptors } from "../services/fileUtils";

const SYSTEM_MESSAGE_ID = -3;

export interface OnSubmitProps {
  message: string;
  //from chat input bar
  currentMessageFiles: ProjectFile[];
  // from the chat bar???

  useAgentSearch: boolean;

  // optional params
  messageIdToResend?: number;
  queryOverride?: string;
  forceSearch?: boolean;
  isSeededChat?: boolean;
  modelOverride?: LlmDescriptor;
  regenerationRequest?: RegenerationRequest | null;
  overrideFileDescriptors?: FileDescriptor[];
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

  // scroll/focus related stuff
  clientScrollToBottom: (fast?: boolean) => void;

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

  // scroll/focus related stuff
  clientScrollToBottom,

  setPopup,
  resetInputBar,
  setSelectedAssistantFromId,
}: UseChatControllerProps) {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const params = useAppParams();
  const { refreshChatSessions, llmProviders } = useChatContext();
  const { agentPreferences: assistantPreferences, forcedToolIds } =
    useAgentsContext();
  const { fetchProjects, uploadFiles, setCurrentMessageFiles, beginUpload } =
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
  const abortSession = useChatSessionStore((state) => state.abortSession);
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

  const upsertToCompleteMessageTree = ({
    messages,
    completeMessageTreeOverride,
    chatSessionId,
    makeLatestChildMessage = false,
  }: {
    messages: Message[];
    // if calling this function repeatedly with short delay, stay may not update in time
    // and result in weird behavipr
    completeMessageTreeOverride?: MessageTreeState | null;
    chatSessionId?: string;
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

    const sessionId = chatSessionId || getCurrentSessionId();
    updateSessionMessageTree(sessionId, newCompleteMessageTree);

    return {
      sessionId,
      messageTree: newCompleteMessageTree,
    };
  };

  const stopGenerating = useCallback(async () => {
    const currentSession = getCurrentSessionId();
    const lastMessage = currentMessageHistory[currentMessageHistory.length - 1];

    // Check if the current message uses agent search (any non-null research type)
    const isDeepResearch = lastMessage?.researchType === ResearchType.Deep;
    const isSimpleAgentFrameworkEnabled =
      posthog.isFeatureEnabled("simple-agent-framework") ?? false;

    // Always call the backend stop endpoint if feature flag is enabled
    if (isSimpleAgentFrameworkEnabled) {
      try {
        await stopChatSession(currentSession);
      } catch (error) {
        console.error("Failed to stop chat session:", error);
        // Continue with UI cleanup even if backend call fails
      }
    }

    // Only do the subsequent cleanup if the message was agent search or feature flag is not enabled
    if (isDeepResearch || !isSimpleAgentFrameworkEnabled) {
      abortSession(currentSession);

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

      // Ensure UI reflects a STOP event by appending a STOP packet to the
      // currently streaming assistant message if one exists and doesn't already
      // contain a STOP. This makes AIMessage behave as if a STOP packet arrived.
      if (lastMessage && lastMessage.type === "assistant") {
        const packets = lastMessage.packets || [];
        const hasStop = packets.some((p) => p.obj.type === PacketType.STOP);
        if (!hasStop) {
          const maxInd =
            packets.length > 0 ? Math.max(...packets.map((p) => p.ind)) : 0;
          const stopPacket: Packet = {
            ind: maxInd + 1,
            obj: { type: PacketType.STOP },
          } as Packet;

          const newMessageTree = new Map(currentMessageTree);
          const updatedMessage = {
            ...lastMessage,
            packets: [...packets, stopPacket],
          } as Message;
          newMessageTree.set(lastMessage.nodeId, updatedMessage);
          updateSessionMessageTree(currentSession, newMessageTree);
        }
      }
    }

    updateChatStateAction(currentSession, "input");
  }, [currentMessageHistory, currentMessageTree, posthog]);

  const onSubmit = useCallback(
    async ({
      message,
      currentMessageFiles,
      useAgentSearch,
      messageIdToResend,
      queryOverride,
      forceSearch,
      isSeededChat,
      modelOverride,
      regenerationRequest,
      overrideFileDescriptors,
    }: OnSubmitProps) => {
      const projectId = params(SEARCH_PARAM_NAMES.PROJECT_ID);
      {
        const params = new URLSearchParams(searchParams?.toString() || "");
        if (params.has(SEARCH_PARAM_NAMES.PROJECT_ID)) {
          params.delete(SEARCH_PARAM_NAMES.PROJECT_ID);
          const newUrl = params.toString()
            ? `${pathname}?${params.toString()}`
            : pathname;
          router.replace(newUrl, { scroll: false });
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

      clientScrollToBottom();

      let currChatSessionId: string;
      const isNewSession = existingChatSessionId === null;

      const searchParamBasedChatSessionName =
        searchParams?.get(SEARCH_PARAM_NAMES.TITLE) || null;
      if (isNewSession) {
        currChatSessionId = await createChatSession(
          liveAssistant?.id || 0,
          searchParamBasedChatSessionName,
          projectId ? parseInt(projectId) : null
        );
      } else {
        currChatSessionId = existingChatSessionId as string;
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
      const newMessageDetails = upsertToCompleteMessageTree({
        messages: messagesToUpsert,
        completeMessageTreeOverride: currentMessageTreeLocal,
        chatSessionId: frozenSessionId,
      });
      resetInputBar();
      currentMessageTreeLocal = newMessageDetails.messageTree;

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

        const stack = new CurrentMessageFIFO();
        updateCurrentMessageFIFO(stack, {
          signal: controller.signal,
          message: currMessage,
          alternateAssistantId: liveAssistant?.id,
          fileDescriptors: overrideFileDescriptors,
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
          selectedDocumentIds: selectedDocuments
            .filter(
              (document) =>
                document.db_doc_id !== undefined && document.db_doc_id !== null
            )
            .map((document) => document.db_doc_id as number),
          queryOverride,
          forceSearch,
          currentMessageFiles: currentMessageFiles.map((file) => ({
            id: file.file_id,
            type: file.chat_file_type,
            name: file.name,
            user_file_id: file.id,
          })),
          regenerate: regenerationRequest !== undefined,
          modelProvider:
            modelOverride?.name || llmManager.currentLlm.name || undefined,
          modelVersion:
            modelOverride?.modelName ||
            llmManager.currentLlm.modelName ||
            searchParams?.get(SEARCH_PARAM_NAMES.MODEL_VERSION) ||
            undefined,
          temperature: llmManager.temperature || undefined,
          systemPromptOverride:
            searchParams?.get(SEARCH_PARAM_NAMES.SYSTEM_PROMPT) || undefined,
          useExistingUserMessage: isSeededChat,
          useAgentSearch,
          enabledToolIds:
            disabledToolIds && liveAssistant
              ? liveAssistant.tools
                  .filter((tool) => !disabledToolIds?.includes(tool.id))
                  .map((tool) => tool.id)
              : undefined,
          forcedToolIds: forcedToolIds,
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
              setUncaughtError(
                frozenSessionId,
                (packet as StreamingError).error
              );
              updateChatStateAction(frozenSessionId, "input");
              updateSubmittedMessage(getCurrentSessionId(), "");

              throw new Error((packet as StreamingError).error);
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

              if (packetObj.type === "citation_delta") {
                const citationDelta = packetObj as CitationDelta;
                if (citationDelta.citations) {
                  citations = Object.fromEntries(
                    citationDelta.citations.map((c) => [
                      c.document_id,
                      c.citation_num,
                    ])
                  );
                }
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

            const newMessageDetails = upsertToCompleteMessageTree({
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
            currentMessageTreeLocal = newMessageDetails.messageTree;
          }
        }
      } catch (e: any) {
        console.log("Error:", e);
        const errorMsg = e.message;
        const newMessageDetails = upsertToCompleteMessageTree({
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
            },
          ],
          completeMessageTreeOverride: currentMessageTreeLocal,
        });
        currentMessageTreeLocal = newMessageDetails.messageTree;
      }

      resetRegenerationState(frozenSessionId);
      updateChatStateAction(frozenSessionId, "input");

      if (isNewSession) {
        if (!searchParamBasedChatSessionName) {
          await new Promise((resolve) => setTimeout(resolve, 200));
          await nameChatSession(currChatSessionId);
          refreshChatSessions();
          fetchProjects();
        }

        // NOTE: don't switch pages if the user has navigated away from the chat
        if (
          currChatSessionId === frozenSessionId ||
          existingChatSessionId === null
        ) {
          const newUrl = buildChatUrl(
            searchParams,
            currChatSessionId,
            null,
            false,
            true
          );
          // newUrl is like /chat?chatId=10
          // current page is like /chat

          if (pathname == "/chat" && !navigatingAway.current) {
            router.push(newUrl, { scroll: false });
            fetchProjects();
          }
        }
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
      clientScrollToBottom,
      resetInputBar,
      setSelectedAssistantFromId,
      updateSelectedNodeForDocDisplay,
      currentMessageTree,
      currentChatState,
      llmProviders,
      // Ensure latest forced tools are used when submitting
      forcedToolIds,
      // Keep tool preference-derived values fresh
      assistantPreferences,
      fetchProjects,
    ]
  );

  const handleMessageSpecificFileUpload = useCallback(
    async (acceptedFiles: File[]) => {
      const [_, llmModel] = getFinalLLM(
        llmProviders,
        liveAssistant || null,
        llmManager.currentLlm
      );
      const llmAcceptsImages = modelSupportsImageInput(llmProviders, llmModel);

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
      const uploadedMessageFiles = await beginUpload(Array.from(acceptedFiles));
      setCurrentMessageFiles((prev) => [...prev, ...uploadedMessageFiles]);
      updateChatStateAction(getCurrentSessionId(), "input");
    },
    [llmProviders, liveAssistant, llmManager, forcedToolIds]
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

  // highlight code blocks and set isReady once that's done
  useEffect(() => {
    Prism.highlightAll();
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
