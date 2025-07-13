import { SessionManager } from "./sessionManager";
import { MessagePreprocessor } from "./messagePreprocessor";
import { StreamingProcessor } from "./streamingProcessor";
import { MessageUpdater } from "./messageUpdater";
import { PostProcessor } from "./postProcessor";
import { sendMessage, SendMessageParams, PacketType } from "../lib";
import { buildFilters } from "@/lib/search/utils";
import { SEARCH_PARAM_NAMES } from "../searchParams";
import { Persona } from "../../admin/assistants/interfaces";
import { Message, FileDescriptor } from "../interfaces";
import { LlmDescriptor, LlmManager } from "@/lib/hooks";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { FilterManager } from "@/lib/hooks";
import { SourceMetadata } from "@/lib/search/interfaces";
import { DocumentSet, Tag, ValidSources } from "@/lib/types";
import { OnyxDocument } from "@/lib/search/interfaces";
import { FileResponse, FolderResponse } from "../my-documents/DocumentsContext";
import { AppRouterInstance } from "next/dist/shared/lib/app-router-context.shared-runtime";
import { RegenerationRequest } from "./messagePreprocessor";
import { ReadonlyURLSearchParams } from "next/navigation";
import { ChatState, RegenerationState } from "../types";

// FIFO Queue for handling streaming packets (matching original implementation)
class CurrentMessageFIFO {
  private stack: PacketType[] = [];
  isComplete: boolean = false;
  error: string | null = null;

  push(packetBunch: PacketType) {
    this.stack.push(packetBunch);
  }

  nextPacket(): PacketType | undefined {
    return this.stack.shift();
  }

  isEmpty(): boolean {
    return this.stack.length === 0;
  }
}

export interface MessageSubmissionDependencies {
  // Session management
  liveAssistant: Persona | undefined;
  searchParams: ReadonlyURLSearchParams | null;
  llmManager: LlmManager;
  chatSessionIdRef: React.MutableRefObject<string | null>;
  updateStatesWithNewSessionId: (newSessionId: string) => void;
  setAbortControllers: React.Dispatch<
    React.SetStateAction<Map<string | null, AbortController>>
  >;

  // Message preprocessing
  currentMessageMap: (
    messageDetail: Map<string | null, Map<number, Message>>
  ) => Map<number, Message>;
  completeMessageDetail: Map<string | null, Map<number, Message>>;
  updateCompleteMessageDetail: (
    sessionId: string | null,
    messageMap: Map<number, Message>
  ) => void;
  messageHistory: Message[];
  setPopup: (popup: PopupSpec | null) => void;
  getCurrentChatState: () => string;
  setAlternativeGeneratingAssistant: (assistant: Persona | null) => void;
  clientScrollToBottom: () => void;
  resetInputBar: () => void;

  // Streaming processing
  updateChatState: (state: ChatState, sessionId?: string | null) => void;
  setAgenticGenerating: (generating: boolean) => void;
  updateCanContinue: (canContinue: boolean, sessionId: string) => void;
  upsertToCompleteMessageMap: (params: {
    messages: Message[];
    replacementsMap?: Map<number, number> | null;
    completeMessageMapOverride?: Map<number, Message> | null;
    chatSessionId?: string;
    makeLatestChildMessage?: boolean;
  }) => {
    sessionId: string;
    messageMap: Map<number, Message>;
  };
  setSelectedMessageForDocDisplay: (messageId: number | null) => void;
  setUncaughtError: (error: string | null) => void;
  setSubmittedMessage: (message: string) => void;

  // Post processing
  resetRegenerationState: (sessionId: string) => void;
  refreshChatSessions: () => void;
  router: AppRouterInstance;
  pathname: string;
  navigatingAway: React.MutableRefObject<boolean>;

  // Other dependencies
  alternativeAssistant: Persona | null;
  message: string;
  currentMessageFiles: FileDescriptor[];
  selectedDocuments: OnyxDocument[];
  selectedFolders: FolderResponse[];
  selectedFiles: FileResponse[];
  filterManager: FilterManager;
  availableSources: ValidSources[];
  documentSets: DocumentSet[];
  tags: Tag[];
  settings: {
    isMobile?: boolean;
    settings?: { pro_search_enabled?: boolean };
  } | null;
  proSearchEnabled: boolean;
  retrievalEnabled: boolean;
  updateRegenerationState: (
    state: RegenerationState | null,
    sessionId?: string | null
  ) => void;
  markSessionMessageSent: (sessionId: string) => void;
  setLoadingError: (error: string | null) => void;
  getCurrentSessionId: () => string;
}

export interface MessageSubmissionParams {
  messageIdToResend?: number;
  messageOverride?: string;
  queryOverride?: string;
  forceSearch?: boolean;
  isSeededChat?: boolean;
  alternativeAssistantOverride?: Persona | null;
  modelOverride?: LlmDescriptor;
  regenerationRequest?: RegenerationRequest | null;
  overrideFileDescriptors?: FileDescriptor[];
}

export class MessageSubmissionService {
  private sessionManager: SessionManager;
  private messagePreprocessor: MessagePreprocessor;
  private streamingProcessor: StreamingProcessor;
  private messageUpdater: MessageUpdater;
  private postProcessor: PostProcessor;

  constructor(private deps: MessageSubmissionDependencies) {
    this.sessionManager = new SessionManager({
      liveAssistant: deps.liveAssistant,
      searchParams: deps.searchParams,
      llmManager: deps.llmManager,
      chatSessionIdRef: deps.chatSessionIdRef,
      updateStatesWithNewSessionId: deps.updateStatesWithNewSessionId,
      setAbortControllers: deps.setAbortControllers,
    });

    this.messagePreprocessor = new MessagePreprocessor({
      currentMessageMap: deps.currentMessageMap,
      completeMessageDetail: deps.completeMessageDetail,
      updateCompleteMessageDetail: deps.updateCompleteMessageDetail,
      messageHistory: deps.messageHistory,
      setPopup: deps.setPopup,
      getCurrentChatState: deps.getCurrentChatState,
      setAlternativeGeneratingAssistant: deps.setAlternativeGeneratingAssistant,
      clientScrollToBottom: deps.clientScrollToBottom,
      resetInputBar: deps.resetInputBar,
    });

    this.streamingProcessor = new StreamingProcessor({
      updateChatState: deps.updateChatState,
      getCurrentChatState: deps.getCurrentChatState,
      setAgenticGenerating: deps.setAgenticGenerating,
      updateCanContinue: deps.updateCanContinue,
      upsertToCompleteMessageMap: deps.upsertToCompleteMessageMap,
      setSelectedMessageForDocDisplay: deps.setSelectedMessageForDocDisplay,
      setUncaughtError: deps.setUncaughtError,
      setLoadingError: deps.setLoadingError,
      setAlternativeGeneratingAssistant: deps.setAlternativeGeneratingAssistant,
      setSubmittedMessage: deps.setSubmittedMessage,
      resetRegenerationState: deps.resetRegenerationState,
    });

    this.messageUpdater = new MessageUpdater({
      upsertToCompleteMessageMap: deps.upsertToCompleteMessageMap,
    });

    this.postProcessor = new PostProcessor({
      setAgenticGenerating: deps.setAgenticGenerating,
      resetRegenerationState: deps.resetRegenerationState,
      updateChatState: deps.updateChatState,
      setSelectedMessageForDocDisplay: deps.setSelectedMessageForDocDisplay,
      setAlternativeGeneratingAssistant: deps.setAlternativeGeneratingAssistant,
      setSubmittedMessage: deps.setSubmittedMessage,
      refreshChatSessions: deps.refreshChatSessions,
      router: deps.router,
      pathname: deps.pathname,
      searchParams: deps.searchParams,
      navigatingAway: deps.navigatingAway,
      chatSessionIdRef: deps.chatSessionIdRef,
    });
  }

  private getLastSuccessfulMessageId(messageHistory: Message[]): number | null {
    // This should be implemented based on the actual logic
    return messageHistory.length > 0
      ? messageHistory[messageHistory.length - 1]?.messageId || null
      : null;
  }

  private async updateCurrentMessageFIFO(
    stack: CurrentMessageFIFO,
    params: SendMessageParams
  ): Promise<void> {
    try {
      for await (const packet of sendMessage(params)) {
        if (params.signal?.aborted) {
          throw new Error("AbortError");
        }
        stack.push(packet);
      }
    } catch (error: unknown) {
      if (error instanceof Error) {
        if (error.name === "AbortError") {
          console.debug("Stream aborted");
        } else {
          stack.error = error.message;
        }
      } else {
        stack.error = String(error);
      }
    } finally {
      stack.isComplete = true;
    }
  }

  async submitMessage(params: MessageSubmissionParams = {}): Promise<void> {
    const {
      messageIdToResend,
      messageOverride,
      queryOverride,
      forceSearch,
      isSeededChat,
      alternativeAssistantOverride = null,
      modelOverride,
      regenerationRequest,
      overrideFileDescriptors,
    } = params;

    // Initialize state
    this.deps.navigatingAway.current = false;
    let frozenSessionId = this.deps.getCurrentSessionId();
    this.deps.updateCanContinue(false, frozenSessionId);
    this.deps.setUncaughtError(null);
    this.deps.setLoadingError(null);

    // Mark that we've sent a message for this session
    this.deps.markSessionMessageSent(frozenSessionId);

    // Preprocess message
    const preprocessingResult = this.messagePreprocessor.preprocessMessage({
      messageIdToResend,
      messageOverride,
      alternativeAssistantOverride,
      regenerationRequest,
      message: this.deps.message,
      alternativeAssistant: this.deps.alternativeAssistant,
      liveAssistant: this.deps.liveAssistant,
      frozenSessionId,
    });

    const {
      currentMap,
      currentHistory,
      parentMessage,
      currentAssistantId,
      currMessage,
      messageToResend,
      messageToResendIndex,
    } = preprocessingResult;

    // Setup session
    const searchParamBasedChatSessionName =
      this.deps.searchParams?.get(SEARCH_PARAM_NAMES.TITLE) || null;
    const sessionSetup = await this.sessionManager.setupSession(
      modelOverride,
      searchParamBasedChatSessionName
    );
    const {
      sessionId: currChatSessionId,
      isNewSession,
      controller,
    } = sessionSetup;
    frozenSessionId = currChatSessionId;

    // Handle regeneration state
    if (messageIdToResend) {
      this.deps.updateRegenerationState(
        { regenerating: true, finalMessageIndex: messageIdToResend },
        frozenSessionId
      );
    }

    // Handle case where messageToResend is not found (matching original logic)
    if (!messageToResend && messageIdToResend !== undefined) {
      this.deps.setPopup({
        message:
          "Failed to re-send message - please refresh the page and try again.",
        type: "error",
      });
      this.deps.resetRegenerationState(frozenSessionId);
      this.deps.updateChatState("input", frozenSessionId);
      return;
    }

    // Set submitted message and update chat state
    this.deps.setSubmittedMessage(currMessage);
    this.deps.updateChatState("loading");

    // Initialize streaming state
    const streamingState = this.streamingProcessor.initializeStreamingState();

    // Prepare send message parameters
    const sendMessageParams: SendMessageParams = {
      signal: controller.signal,
      message: currMessage,
      alternateAssistantId: currentAssistantId,
      fileDescriptors: overrideFileDescriptors || this.deps.currentMessageFiles,
      parentMessageId:
        regenerationRequest?.parentMessage.messageId ||
        this.getLastSuccessfulMessageId(currentHistory),
      chatSessionId: currChatSessionId,
      filters: buildFilters(
        this.deps.filterManager.selectedSources,
        this.deps.filterManager.selectedDocumentSets,
        this.deps.filterManager.timeRange,
        this.deps.filterManager.selectedTags
      ),
      selectedDocumentIds: this.deps.selectedDocuments
        .filter(
          (document) =>
            document.db_doc_id !== undefined && document.db_doc_id !== null
        )
        .map((document) => document.db_doc_id as number),
      queryOverride,
      forceSearch,
      userFolderIds: this.deps.selectedFolders.map((folder) => folder.id),
      userFileIds: this.deps.selectedFiles
        .filter((file) => file.id !== undefined && file.id !== null)
        .map((file) => file.id),
      regenerate: regenerationRequest !== undefined,
      modelProvider:
        modelOverride?.name ||
        this.deps.llmManager.currentLlm.name ||
        undefined,
      modelVersion:
        modelOverride?.modelName ||
        this.deps.llmManager.currentLlm.modelName ||
        this.deps.searchParams?.get(SEARCH_PARAM_NAMES.MODEL_VERSION) ||
        undefined,
      temperature: this.deps.llmManager.temperature || undefined,
      systemPromptOverride:
        this.deps.searchParams?.get(SEARCH_PARAM_NAMES.SYSTEM_PROMPT) ||
        undefined,
      useExistingUserMessage: isSeededChat,
      useLanggraph:
        this.deps.settings?.settings?.pro_search_enabled &&
        this.deps.proSearchEnabled &&
        this.deps.retrievalEnabled,
    };

    // Process streaming
    let initialFetchDetails: {
      user_message_id: number;
      assistant_message_id: number;
      frozenMessageMap: Map<number, Message>;
    } | null = null;
    let currentMapCopy = new Map(currentMap);

    try {
      const mapKeys = Array.from(currentMapCopy.keys());
      const stack = new CurrentMessageFIFO();

      // Start streaming
      this.updateCurrentMessageFIFO(stack, sendMessageParams);

      const delay = (ms: number) =>
        new Promise((resolve) => setTimeout(resolve, ms));
      await delay(50);

      while (!stack.isComplete || !stack.isEmpty()) {
        if (stack.isEmpty()) {
          await delay(0.5);
        }

        if (!stack.isEmpty() && !controller.signal.aborted) {
          const packet = stack.nextPacket();
          if (!packet) continue;

          console.log("Packet:", JSON.stringify(packet));

          if (!initialFetchDetails) {
            initialFetchDetails = this.streamingProcessor.processInitialPacket(
              packet,
              regenerationRequest || null,
              currMessage,
              parentMessage,
              currentMapCopy,
              currChatSessionId,
              streamingState.files
            );
            if (!initialFetchDetails) continue;
          } else {
            // Process packet and update streaming state
            const newStreamingState = this.streamingProcessor.processPacket(
              packet,
              streamingState,
              frozenSessionId,
              initialFetchDetails.user_message_id
            );

            // Update messages
            currentMapCopy = this.messageUpdater.updateMessages({
              regenerationRequest: regenerationRequest || null,
              initialFetchDetails,
              streamingState: newStreamingState,
              currMessage,
              parentMessage,
              currentMap: currentMapCopy,
              frozenSessionId,
              alternativeAssistant: this.deps.alternativeAssistant,
              mapKeys,
            });

            // Update streaming state
            Object.assign(streamingState, newStreamingState);
          }
        }
      }
    } catch (e: unknown) {
      console.log("Error:", e);
      const errorMsg = e instanceof Error ? e.message : String(e);

      // Handle error by creating error messages
      this.deps.upsertToCompleteMessageMap({
        messages: [
          {
            messageId: initialFetchDetails?.user_message_id || -1,
            message: currMessage,
            type: "user",
            files: this.deps.currentMessageFiles,
            toolCall: null,
            parentMessageId: parentMessage?.messageId || -3,
          },
          {
            messageId: initialFetchDetails?.assistant_message_id || -2,
            message: errorMsg,
            type: "error",
            files: streamingState.aiMessageImages || [],
            toolCall: null,
            parentMessageId: initialFetchDetails?.user_message_id || -1,
          },
        ],
        completeMessageMapOverride: currentMapCopy,
      });
    }

    // Post-processing
    await this.postProcessor.processPostSubmission({
      isNewSession,
      sessionId: currChatSessionId,
      finalMessage: streamingState.finalMessage,
      retrievalType: streamingState.retrievalType,
      searchParamBasedChatSessionName,
    });
  }
}
