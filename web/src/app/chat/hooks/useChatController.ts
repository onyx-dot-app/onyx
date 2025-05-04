import {
  buildChatUrl,
  nameChatSession,
  processRawChatHistory,
  patchMessageToBeLatest,
} from "../services/lib";

import {
  AgentAnswerPiece,
  DocumentInfoPacket,
  RefinedAnswerImprovement,
  StreamStopInfo,
  SubQueryPiece,
  SubQuestionPiece,
} from "@/lib/search/interfaces";

import { AnswerPiecePacket } from "@/lib/search/interfaces";

import {
  Dispatch,
  SetStateAction,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  getLastSuccessfulMessageId,
  getLatestMessageChain,
  MessageTreeState,
  removeMessage,
  setMessageAsLatest,
  upsertMessages,
} from "../services/messageTree";
import { Persona } from "@/app/admin/assistants/interfaces";
import { updateLlmOverrideForChatSession } from "../services/lib";
import {
  SEARCH_PARAM_NAMES,
  shouldSubmitOnLoad,
} from "../services/searchParams";
import { OnyxDocument } from "@/lib/search/interfaces";
import { SEARCH_TOOL_NAME } from "../components/tools/constants";
import { FilterManager, LlmDescriptor, LlmManager } from "@/lib/hooks";
import {
  AgenticMessageResponseIDInfo,
  BackendChatSession,
  BackendMessage,
  ChatFileType,
  ChatSessionSharedStatus,
  ChatState,
  DocumentsResponse,
  FileChatDisplay,
  FileDescriptor,
  Message,
  MessageResponseIDInfo,
  RegenerationState,
  RetrievalType,
  StreamingError,
  SubQuestionDetail,
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
import { constructSubQuestions } from "../services/constructSubQuestions";
import {
  ReadonlyURLSearchParams,
  usePathname,
  useRouter,
  useSearchParams,
} from "next/navigation";
import {
  FileResponse,
  FolderResponse,
  useDocumentsContext,
} from "../my-documents/DocumentsContext";
import { useChatContext } from "@/components/context/ChatContext";
import Prism from "prismjs";
import { UploadIntent } from "../components/ChatPage";

const TEMP_USER_MESSAGE_ID = -1;
const TEMP_ASSISTANT_MESSAGE_ID = -2;
const SYSTEM_MESSAGE_ID = -3;

interface RegenerationRequest {
  messageId: number;
  parentMessage: Message;
  forceSearch?: boolean;
}

interface UseChatControllerProps {
  filterManager: FilterManager;
  llmManager: LlmManager;
  liveAssistant: Persona;
  availableAssistants: Persona[];
  existingChatSessionId: string | null;
  firstMessage?: string;
  selectedDocuments: OnyxDocument[];
  searchParams: ReadonlyURLSearchParams;
  setPopup: (popup: PopupSpec) => void;

  // scroll/focus related stuff
  clientScrollToBottom: (fast?: boolean) => void;
  scrollInitialized: React.MutableRefObject<boolean>;
  hasPerformedInitialScroll: boolean;
  setHasPerformedInitialScroll: React.Dispatch<React.SetStateAction<boolean>>;
  isInitialLoad: React.MutableRefObject<boolean>;
  textAreaRef: React.RefObject<HTMLTextAreaElement>;

  resetInputBar: () => void;
  setSelectedAssistantFromId: (assistantId: number | null) => void;
  setSelectedMessageForDocDisplay: (messageId: number | null) => void;
  setSelectedDocuments: (documents: OnyxDocument[]) => void;
}

export function useChatController({
  filterManager,
  llmManager,
  availableAssistants,
  liveAssistant,
  existingChatSessionId,
  firstMessage,
  selectedDocuments,

  // scroll/focus related stuff
  clientScrollToBottom,
  scrollInitialized,
  hasPerformedInitialScroll,
  setHasPerformedInitialScroll,
  isInitialLoad,
  textAreaRef,

  setPopup,
  resetInputBar,
  setSelectedAssistantFromId,
  setSelectedMessageForDocDisplay,
  setSelectedDocuments,
}: UseChatControllerProps) {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const { refreshChatSessions, llmProviders } = useChatContext();

  const {
    selectedFiles,
    selectedFolders,
    addSelectedFile,
    uploadFile,
    setCurrentMessageFiles,
    clearSelectedItems,
  } = useDocumentsContext();

  const chatSessionIdRef = useRef<string | null>(existingChatSessionId);
  // Only updates on session load (ie. rename / switching chat session)
  // Useful for determining which session has been loaded
  // (i.e. still on `new, empty session` or `previous session`)
  const loadedIdSessionRef = useRef<string | null>(existingChatSessionId);

  // used to track whether or not the initial "submit on load" has been performed
  // this only applies if `?submit-on-load=true` or `?submit-on-load=1` is in the URL
  // NOTE: this is required due to React strict mode, where all `useEffect` hooks
  // are run twice on initial load during development
  const submitOnLoadPerformed = useRef<boolean>(false);

  const navigatingAway = useRef(false);

  const [isReady, setIsReady] = useState(false);

  // just choose a conservative default, this will be updated in the
  // background on initial load / on persona change
  const [maxTokens, setMaxTokens] = useState<number>(4096);

  // fetch messages for the chat session
  const [isFetchingChatMessages, setIsFetchingChatMessages] = useState(
    existingChatSessionId !== null
  );
  const [submittedMessage, setSubmittedMessage] = useState(firstMessage || "");

  const [canContinue, setCanContinue] = useState<Map<string | null, boolean>>(
    new Map([[null, false]])
  );

  const [agenticGenerating, setAgenticGenerating] = useState(false);

  const [uncaughtError, setUncaughtError] = useState<string | null>(null);
  const [loadingError, setLoadingError] = useState<string | null>(null);

  const [completeMessageDetail, setCompleteMessageDetail] = useState<
    Map<string | null, MessageTreeState>
  >(new Map());

  const [chatState, setChatState] = useState<Map<string | null, ChatState>>(
    new Map([[chatSessionIdRef.current, firstMessage ? "loading" : "input"]])
  );

  const [chatSessionSharedStatus, setChatSessionSharedStatus] =
    useState<ChatSessionSharedStatus>(ChatSessionSharedStatus.Private);

  const [regenerationState, setRegenerationState] = useState<
    Map<string | null, RegenerationState | null>
  >(new Map([[null, null]]));

  const [abortControllers, setAbortControllers] = useState<
    Map<string | null, AbortController>
  >(new Map());

  const abortControllersRef = useRef(abortControllers);
  useEffect(() => {
    abortControllersRef.current = abortControllers;
  }, [abortControllers]);

  const updateRegenerationState = (
    newState: RegenerationState | null,
    sessionId?: string | null
  ) => {
    const newRegenerationState = new Map(regenerationState);
    newRegenerationState.set(
      sessionId !== undefined && sessionId != null
        ? sessionId
        : currentSessionId(),
      newState
    );

    setRegenerationState((prevState) => {
      const newRegenerationState = new Map(prevState);
      newRegenerationState.set(
        sessionId !== undefined && sessionId != null
          ? sessionId
          : currentSessionId(),
        newState
      );
      return newRegenerationState;
    });
  };

  const updateChatState = (newState: ChatState, sessionId?: string | null) => {
    setChatState((prevState) => {
      const newChatState = new Map(prevState);
      newChatState.set(
        sessionId !== undefined ? sessionId : currentSessionId(),
        newState
      );
      return newChatState;
    });
  };

  const resetRegenerationState = (sessionId?: string | null) => {
    updateRegenerationState(null, sessionId);
  };

  const updateStatesWithNewSessionId = (newSessionId: string) => {
    const updateState = (
      setState: Dispatch<SetStateAction<Map<string | null, any>>>,
      defaultValue?: any
    ) => {
      setState((prevState) => {
        const newState = new Map(prevState);
        const existingState = newState.get(null);
        if (existingState !== undefined) {
          newState.set(newSessionId, existingState);
          newState.delete(null);
        } else if (defaultValue !== undefined) {
          newState.set(newSessionId, defaultValue);
        }
        return newState;
      });
    };

    updateState(setRegenerationState);
    updateState(setChatState);
    updateState(setAbortControllers);

    // Update completeMessageDetail
    setCompleteMessageDetail((prevState) => {
      const newState = new Map(prevState);
      const existingMessages = newState.get(null);
      if (existingMessages) {
        newState.set(newSessionId, existingMessages);
        newState.delete(null);
      }
      return newState;
    });

    // Update chatSessionIdRef
    chatSessionIdRef.current = newSessionId;
  };

  const updateCompleteMessageDetail = (
    sessionId: string | null,
    messageMap: Map<number, Message>
  ) => {
    setCompleteMessageDetail((prevState) => {
      const newState = new Map(prevState);
      newState.set(sessionId, messageMap);
      return newState;
    });
  };

  const currentMessageMap = (
    messageDetail: Map<string | null, Map<number, Message>>
  ) => {
    return (
      messageDetail.get(chatSessionIdRef.current) || new Map<number, Message>()
    );
  };

  const currentSessionId = (): string => {
    return chatSessionIdRef.current!;
  };

  const upsertToCompleteMessageMap = ({
    messages,
    completeMessageMapOverride,
    chatSessionId,
    oldIds,
    makeLatestChildMessage = false,
  }: {
    messages: Message[];
    // if calling this function repeatedly with short delay, stay may not update in time
    // and result in weird behavipr
    completeMessageMapOverride?: Map<number, Message> | null;
    chatSessionId?: string;
    oldIds?: number[] | null;
    makeLatestChildMessage?: boolean;
  }) => {
    console.log(messages);
    let currentMap =
      completeMessageMapOverride ||
      (chatSessionId !== undefined &&
        completeMessageDetail.get(chatSessionId)) ||
      currentMessageMap(completeMessageDetail);

    if (oldIds) {
      oldIds.forEach((id) => {
        removeMessage(currentMap, id);
      });
    }

    const newCompleteMessageMap = upsertMessages(
      currentMap,
      messages,
      makeLatestChildMessage
    );

    const newCompleteMessageDetail = {
      sessionId: chatSessionId || currentSessionId(),
      messageMap: newCompleteMessageMap,
    };

    updateCompleteMessageDetail(
      chatSessionId || currentSessionId(),
      newCompleteMessageMap
    );
    console.log(newCompleteMessageDetail);
    return newCompleteMessageDetail;
  };

  const updateCanContinue = (newState: boolean, sessionId?: string | null) => {
    setCanContinue((prevState) => {
      const newCanContinueState = new Map(prevState);
      newCanContinueState.set(
        sessionId !== undefined ? sessionId : currentSessionId(),
        newState
      );
      return newCanContinueState;
    });
  };

  const currentChatState = (): ChatState => {
    return chatState.get(currentSessionId()) || "input";
  };

  const stopGenerating = () => {
    const currentSession = currentSessionId();
    const controller = abortControllers.get(currentSession);
    if (controller) {
      controller.abort();
      setAbortControllers((prev) => {
        const newControllers = new Map(prev);
        newControllers.delete(currentSession);
        return newControllers;
      });
    }

    const lastMessage = messageHistory[messageHistory.length - 1];
    if (
      lastMessage &&
      lastMessage.type === "assistant" &&
      lastMessage.toolCall &&
      lastMessage.toolCall.tool_result === undefined
    ) {
      const newCompleteMessageMap = new Map(
        currentMessageMap(completeMessageDetail)
      );
      const updatedMessage = { ...lastMessage, toolCall: null };
      newCompleteMessageMap.set(lastMessage.messageId, updatedMessage);
      updateCompleteMessageDetail(currentSession, newCompleteMessageMap);
    }

    updateChatState("input", currentSession);
  };

  const onSubmit = async ({
    message,
    selectedFiles,
    selectedFolders,
    currentMessageFiles,
    useLanggraph,
    messageIdToResend,
    queryOverride,
    forceSearch,
    isSeededChat,
    alternativeAssistantOverride = null,
    modelOverride,
    regenerationRequest,
    overrideFileDescriptors,
  }: {
    message: string;
    // from MyDocuments
    selectedFiles: FileResponse[];
    selectedFolders: FolderResponse[];
    // from the chat bar???
    currentMessageFiles: FileDescriptor[];
    useLanggraph: boolean;

    // optional params
    messageIdToResend?: number;
    queryOverride?: string;
    forceSearch?: boolean;
    isSeededChat?: boolean;
    alternativeAssistantOverride?: Persona | null;
    modelOverride?: LlmDescriptor;
    regenerationRequest?: RegenerationRequest | null;
    overrideFileDescriptors?: FileDescriptor[];
  }) => {
    setSubmittedMessage(message);

    navigatingAway.current = false;
    let frozenSessionId = currentSessionId();
    updateCanContinue(false, frozenSessionId);
    setUncaughtError(null);
    setLoadingError(null);

    // Check if the last message was an error and remove it before proceeding with a new message
    // Ensure this isn't a regeneration or resend, as those operations should preserve the history leading up to the point of regeneration/resend.
    let currentMap = currentMessageMap(completeMessageDetail);
    let currentHistory = getLatestMessageChain(currentMap);
    let lastMessage = currentHistory[currentHistory.length - 1];

    if (
      lastMessage &&
      lastMessage.type === "error" &&
      !messageIdToResend &&
      !regenerationRequest
    ) {
      const newMap = new Map(currentMap);
      const parentId = lastMessage.parentMessageId;

      // Remove the error message itself
      newMap.delete(lastMessage.messageId);

      // Remove the parent message + update the parent of the parent to no longer
      // link to the parent
      if (parentId !== null && parentId !== undefined) {
        const parentOfError = newMap.get(parentId);
        if (parentOfError) {
          const grandparentId = parentOfError.parentMessageId;
          if (grandparentId !== null && grandparentId !== undefined) {
            const grandparent = newMap.get(grandparentId);
            if (grandparent) {
              // Update grandparent to no longer link to parent
              const updatedGrandparent = {
                ...grandparent,
                childrenMessageIds: (
                  grandparent.childrenMessageIds || []
                ).filter((id) => id !== parentId),
                latestChildMessageId:
                  grandparent.latestChildMessageId === parentId
                    ? null
                    : grandparent.latestChildMessageId,
              };
              newMap.set(grandparentId, updatedGrandparent);
            }
          }
          // Remove the parent message
          newMap.delete(parentId);
        }
      }
      // Update the state immediately so subsequent logic uses the cleaned map
      updateCompleteMessageDetail(frozenSessionId, newMap);
      console.log("Removed previous error message ID:", lastMessage.messageId);

      // update state for the new world (with the error message removed)
      currentHistory = getLatestMessageChain(newMap);
      currentMap = newMap;
      lastMessage = currentHistory[currentHistory.length - 1];
    }

    if (currentChatState() != "input") {
      if (currentChatState() == "uploading") {
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

    // setAlternativeGeneratingAssistant(alternativeAssistantOverride);

    clientScrollToBottom();

    let currChatSessionId: string;
    const isNewSession = chatSessionIdRef.current === null;

    const searchParamBasedChatSessionName =
      searchParams?.get(SEARCH_PARAM_NAMES.TITLE) || null;

    if (isNewSession) {
      currChatSessionId = await createChatSession(
        liveAssistant?.id || 0,
        searchParamBasedChatSessionName
      );
    } else {
      currChatSessionId = chatSessionIdRef.current as string;
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

    updateStatesWithNewSessionId(currChatSessionId);

    const controller = new AbortController();

    setAbortControllers((prev) =>
      new Map(prev).set(currChatSessionId, controller)
    );

    const messageToResend = currentHistory.find(
      (message) => message.messageId === messageIdToResend
    );
    if (messageIdToResend) {
      updateRegenerationState(
        { regenerating: true, finalMessageIndex: messageIdToResend },
        currentSessionId()
      );
    }
    const messageToResendParent =
      messageToResend?.parentMessageId !== null &&
      messageToResend?.parentMessageId !== undefined
        ? currentMap.get(messageToResend.parentMessageId)
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
      resetRegenerationState(currentSessionId());
      updateChatState("input", frozenSessionId);
      return;
    }
    let currMessage = messageToResend ? messageToResend.message : message;

    updateChatState("loading");

    const currMessageHistory =
      messageToResendIndex !== null
        ? currentHistory.slice(0, messageToResendIndex)
        : currentHistory;

    let parentMessage =
      messageToResendParent ||
      (currMessageHistory.length > 0
        ? currMessageHistory[currMessageHistory.length - 1]
        : null) ||
      (currentMap.size === 1 ? Array.from(currentMap.values())[0] : null);

    resetInputBar();
    let messageUpdates: Message[] | null = null;

    let answer = "";
    let second_level_answer = "";

    const stopReason: StreamStopReason | null = null;
    let query: string | null = null;
    let retrievalType: RetrievalType =
      selectedDocuments.length > 0
        ? RetrievalType.SelectedDocs
        : RetrievalType.None;
    let documents: OnyxDocument[] = selectedDocuments;
    let aiMessageImages: FileDescriptor[] | null = null;
    let agenticDocs: OnyxDocument[] | null = null;
    let error: string | null = null;
    let stackTrace: string | null = null;

    let sub_questions: SubQuestionDetail[] = [];
    let is_generating: boolean = false;
    let second_level_generating: boolean = false;
    let finalMessage: BackendMessage | null = null;
    let toolCall: ToolCallMetadata | null = null;
    let isImprovement: boolean | undefined = undefined;
    let isStreamingQuestions = true;
    let includeAgentic = false;
    let secondLevelMessageId: number | null = null;
    let isAgentic: boolean = false;
    let files: FileDescriptor[] = [];

    let initialFetchDetails: null | {
      user_message_id: number;
      assistant_message_id: number;
      frozenMessageMap: Map<number, Message>;
    } = null;
    try {
      const mapKeys = Array.from(currentMap.keys());
      const lastSuccessfulMessageId = getLastSuccessfulMessageId(currentMap);

      const stack = new CurrentMessageFIFO();

      updateCurrentMessageFIFO(stack, {
        signal: controller.signal,
        message: currMessage,
        alternateAssistantId: liveAssistant.id,
        fileDescriptors: overrideFileDescriptors || currentMessageFiles,
        parentMessageId:
          regenerationRequest?.parentMessage.messageId ||
          lastSuccessfulMessageId,
        chatSessionId: currChatSessionId,
        filters: buildFilters(
          filterManager.selectedSources,
          filterManager.selectedDocumentSets,
          filterManager.timeRange,
          filterManager.selectedTags,
          selectedFiles.map((file) => file.id),
          selectedFolders.map((folder) => folder.id)
        ),
        selectedDocumentIds: selectedDocuments
          .filter(
            (document) =>
              document.db_doc_id !== undefined && document.db_doc_id !== null
          )
          .map((document) => document.db_doc_id as number),
        queryOverride,
        forceSearch,
        userFolderIds: selectedFolders.map((folder) => folder.id),
        userFileIds: selectedFiles
          .filter((file) => file.id !== undefined && file.id !== null)
          .map((file) => file.id),

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
        useLanggraph,
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

          if (!initialFetchDetails) {
            if (!Object.hasOwn(packet, "user_message_id")) {
              console.error(
                "First packet should contain message response info "
              );
              if (Object.hasOwn(packet, "error")) {
                const error = (packet as StreamingError).error;
                setLoadingError(error);
                updateChatState("input");
                return;
              }
              continue;
            }

            const messageResponseIDInfo = packet as MessageResponseIDInfo;

            const user_message_id = messageResponseIDInfo.user_message_id!;
            const assistant_message_id =
              messageResponseIDInfo.reserved_assistant_message_id;

            // we will use tempMessages until the regenerated message is complete
            messageUpdates = [
              {
                messageId: regenerationRequest
                  ? regenerationRequest?.parentMessage?.messageId!
                  : user_message_id,
                message: currMessage,
                type: "user",
                files: files,
                toolCall: null,
                parentMessageId: parentMessage?.messageId || SYSTEM_MESSAGE_ID,
              },
            ];

            if (parentMessage && !regenerationRequest) {
              messageUpdates.push({
                ...parentMessage,
                childrenMessageIds: (
                  parentMessage.childrenMessageIds || []
                ).concat([user_message_id]),
                latestChildMessageId: user_message_id,
              });
            }

            const { messageMap: currentFrozenMessageMap } =
              upsertToCompleteMessageMap({
                messages: messageUpdates,
                chatSessionId: currChatSessionId,
                completeMessageMapOverride: currentMap,
              });
            currentMap = currentFrozenMessageMap;

            initialFetchDetails = {
              frozenMessageMap: currentMap,
              assistant_message_id,
              user_message_id,
            };

            resetRegenerationState();
          } else {
            const { user_message_id, frozenMessageMap } = initialFetchDetails;
            if (Object.hasOwn(packet, "agentic_message_ids")) {
              const agenticMessageIds = (packet as AgenticMessageResponseIDInfo)
                .agentic_message_ids;
              const level1MessageId = agenticMessageIds.find(
                (item) => item.level === 1
              )?.message_id;
              if (level1MessageId) {
                secondLevelMessageId = level1MessageId;
                includeAgentic = true;
              }
            }

            setChatState((prevState) => {
              if (prevState.get(chatSessionIdRef.current!) === "loading") {
                return new Map(prevState).set(
                  chatSessionIdRef.current!,
                  "streaming"
                );
              }
              return prevState;
            });

            if (Object.hasOwn(packet, "level")) {
              if ((packet as any).level === 1) {
                second_level_generating = true;
              }
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
            if (Object.hasOwn(packet, "is_agentic")) {
              isAgentic = (packet as any).is_agentic;
            }

            if (Object.hasOwn(packet, "refined_answer_improvement")) {
              isImprovement = (packet as RefinedAnswerImprovement)
                .refined_answer_improvement;
            }

            if (Object.hasOwn(packet, "stream_type")) {
              if ((packet as any).stream_type == "main_answer") {
                is_generating = false;
                second_level_generating = true;
              }
            }

            // // Continuously refine the sub_questions based on the packets that we receive
            if (
              Object.hasOwn(packet, "stop_reason") &&
              Object.hasOwn(packet, "level_question_num")
            ) {
              if ((packet as StreamStopInfo).stream_type == "main_answer") {
                updateChatState("streaming", frozenSessionId);
              }
              if (
                (packet as StreamStopInfo).stream_type == "sub_questions" &&
                (packet as StreamStopInfo).level_question_num == undefined
              ) {
                isStreamingQuestions = false;
              }
              sub_questions = constructSubQuestions(
                sub_questions,
                packet as StreamStopInfo
              );
            } else if (Object.hasOwn(packet, "sub_question")) {
              updateChatState("toolBuilding", frozenSessionId);
              isAgentic = true;
              is_generating = true;
              sub_questions = constructSubQuestions(
                sub_questions,
                packet as SubQuestionPiece
              );
              setAgenticGenerating(true);
            } else if (Object.hasOwn(packet, "sub_query")) {
              sub_questions = constructSubQuestions(
                sub_questions,
                packet as SubQueryPiece
              );
            } else if (
              Object.hasOwn(packet, "answer_piece") &&
              Object.hasOwn(packet, "answer_type") &&
              (packet as AgentAnswerPiece).answer_type === "agent_sub_answer"
            ) {
              sub_questions = constructSubQuestions(
                sub_questions,
                packet as AgentAnswerPiece
              );
            } else if (Object.hasOwn(packet, "answer_piece")) {
              // Mark every sub_question's is_generating as false
              sub_questions = sub_questions.map((subQ) => ({
                ...subQ,
                is_generating: false,
              }));

              if (
                Object.hasOwn(packet, "level") &&
                (packet as any).level === 1
              ) {
                second_level_answer += (packet as AnswerPiecePacket)
                  .answer_piece;
              } else {
                answer += (packet as AnswerPiecePacket).answer_piece;
              }
            } else if (
              Object.hasOwn(packet, "top_documents") &&
              Object.hasOwn(packet, "level_question_num") &&
              (packet as DocumentsResponse).level_question_num != undefined
            ) {
              const documentsResponse = packet as DocumentsResponse;
              sub_questions = constructSubQuestions(
                sub_questions,
                documentsResponse
              );

              if (
                documentsResponse.level_question_num === 0 &&
                documentsResponse.level == 0
              ) {
                documents = (packet as DocumentsResponse).top_documents;
              } else if (
                documentsResponse.level_question_num === 0 &&
                documentsResponse.level == 1
              ) {
                agenticDocs = (packet as DocumentsResponse).top_documents;
              }
            } else if (Object.hasOwn(packet, "top_documents")) {
              documents = (packet as DocumentInfoPacket).top_documents;
              retrievalType = RetrievalType.Search;

              if (documents && documents.length > 0) {
                // point to the latest message (we don't know the messageId yet, which is why
                // we have to use -1)
                setSelectedMessageForDocDisplay(user_message_id);
              }
            } else if (Object.hasOwn(packet, "tool_name")) {
              // Will only ever be one tool call per message
              toolCall = {
                tool_name: (packet as ToolCallMetadata).tool_name,
                tool_args: (packet as ToolCallMetadata).tool_args,
                tool_result: (packet as ToolCallMetadata).tool_result,
              };

              if (!toolCall.tool_name.includes("agent")) {
                if (
                  !toolCall.tool_result ||
                  toolCall.tool_result == undefined
                ) {
                  updateChatState("toolBuilding", frozenSessionId);
                } else {
                  updateChatState("streaming", frozenSessionId);
                }

                // This will be consolidated in upcoming tool calls udpate,
                // but for now, we need to set query as early as possible
                if (toolCall.tool_name == SEARCH_TOOL_NAME) {
                  query = toolCall.tool_args["query"];
                }
              } else {
                toolCall = null;
              }
            } else if (Object.hasOwn(packet, "file_ids")) {
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
              if (
                sub_questions.length > 0 &&
                sub_questions
                  .filter((q) => q.level === 0)
                  .every((q) => q.is_stopped === true)
              ) {
                setUncaughtError((packet as StreamingError).error);
                updateChatState("input");
                setAgenticGenerating(false);
                // setAlternativeGeneratingAssistant(null);
                setSubmittedMessage("");

                throw new Error((packet as StreamingError).error);
              } else {
                error = (packet as StreamingError).error;
                stackTrace = (packet as StreamingError).stack_trace;
              }
            } else if (Object.hasOwn(packet, "message_id")) {
              finalMessage = packet as BackendMessage;
            } else if (Object.hasOwn(packet, "stop_reason")) {
              const stop_reason = (packet as StreamStopInfo).stop_reason;
              if (stop_reason === StreamStopReason.CONTEXT_LENGTH) {
                updateCanContinue(true, frozenSessionId);
              }
            }

            // on initial message send, we insert a dummy system message
            // set this as the parent here if no parent is set
            parentMessage =
              parentMessage || frozenMessageMap?.get(SYSTEM_MESSAGE_ID)!;

            const updateFn = (messages: Message[]) => {
              const oldIds =
                regenerationRequest && initialFetchDetails?.assistant_message_id
                  ? [regenerationRequest.messageId]
                  : null;

              const newMessageDetails = upsertToCompleteMessageMap({
                messages: messages,
                oldIds: oldIds,
                // Pass the latest map state
                completeMessageMapOverride: currentMap,
                chatSessionId: frozenSessionId!,
              });
              currentMap = newMessageDetails.messageMap;
              return newMessageDetails;
            };

            const systemMessageId = Math.min(...mapKeys);
            updateFn([
              {
                messageId: regenerationRequest
                  ? regenerationRequest?.parentMessage?.messageId!
                  : initialFetchDetails.user_message_id!,
                message: currMessage,
                type: "user",
                files: files,
                toolCall: null,
                // in the frontend, every message should have a parent ID
                parentMessageId: lastSuccessfulMessageId ?? systemMessageId,
                childrenMessageIds: [
                  ...(regenerationRequest?.parentMessage?.childrenMessageIds ||
                    []),
                  initialFetchDetails.assistant_message_id!,
                ],
                latestChildMessageId: initialFetchDetails.assistant_message_id,
              },
              {
                isStreamingQuestions: isStreamingQuestions,
                is_generating: is_generating,
                isImprovement: isImprovement,
                messageId: initialFetchDetails.assistant_message_id!,
                message: error || answer,
                second_level_message: second_level_answer,
                type: error ? "error" : "assistant",
                retrievalType,
                query: finalMessage?.rephrased_query || query,
                documents: documents,
                citations: finalMessage?.citations || {},
                files: finalMessage?.files || aiMessageImages || [],
                toolCall: finalMessage?.tool_call || toolCall,
                parentMessageId: regenerationRequest
                  ? regenerationRequest?.parentMessage?.messageId!
                  : initialFetchDetails.user_message_id,
                // alternateAssistantID: alternativeAssistant?.id,
                stackTrace: stackTrace,
                overridden_model: finalMessage?.overridden_model,
                stopReason: stopReason,
                sub_questions: sub_questions,
                second_level_generating: second_level_generating,
                agentic_docs: agenticDocs,
                is_agentic: isAgentic,
              },
              ...(includeAgentic
                ? [
                    {
                      messageId: secondLevelMessageId!,
                      message: second_level_answer,
                      type: "assistant" as const,
                      files: [],
                      toolCall: null,
                      parentMessageId:
                        initialFetchDetails.assistant_message_id!,
                    },
                  ]
                : []),
            ]);
          }
        }
      }
    } catch (e: any) {
      console.log("Error:", e);
      const errorMsg = e.message;
      const newMessageDetails = upsertToCompleteMessageMap({
        messages: [
          {
            messageId:
              initialFetchDetails?.user_message_id || TEMP_USER_MESSAGE_ID,
            message: currMessage,
            type: "user",
            files: currentMessageFiles,
            toolCall: null,
            parentMessageId: parentMessage?.messageId || SYSTEM_MESSAGE_ID,
          },
          {
            messageId:
              initialFetchDetails?.assistant_message_id ||
              TEMP_ASSISTANT_MESSAGE_ID,
            message: errorMsg,
            type: "error",
            files: aiMessageImages || [],
            toolCall: null,
            parentMessageId:
              initialFetchDetails?.user_message_id || TEMP_USER_MESSAGE_ID,
          },
        ],
        completeMessageMapOverride: currentMap,
      });
      currentMap = newMessageDetails.messageMap;
    }
    console.log("Finished streaming");
    setAgenticGenerating(false);
    resetRegenerationState(currentSessionId());

    updateChatState("input");
    if (isNewSession) {
      console.log("Setting up new session");
      if (finalMessage) {
        setSelectedMessageForDocDisplay(finalMessage.message_id);
      }

      if (!searchParamBasedChatSessionName) {
        await new Promise((resolve) => setTimeout(resolve, 200));
        await nameChatSession(currChatSessionId);
        refreshChatSessions();
      }

      // NOTE: don't switch pages if the user has navigated away from the chat
      if (
        currChatSessionId === chatSessionIdRef.current ||
        chatSessionIdRef.current === null
      ) {
        const newUrl = buildChatUrl(searchParams, currChatSessionId, null);
        // newUrl is like /chat?chatId=10
        // current page is like /chat

        if (pathname == "/chat" && !navigatingAway.current) {
          router.push(newUrl, { scroll: false });
        }
      }
    }
    if (
      finalMessage?.context_docs &&
      finalMessage.context_docs.top_documents.length > 0 &&
      retrievalType === RetrievalType.Search
    ) {
      setSelectedMessageForDocDisplay(finalMessage.message_id);
    }
    // setAlternativeGeneratingAssistant(null);
    // setSubmittedMessage("");
  };

  const handleImageUpload = async (
    acceptedFiles: File[],
    intent: UploadIntent
  ) => {
    const [_, llmModel] = getFinalLLM(
      llmProviders,
      liveAssistant,
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

    updateChatState("uploading", currentSessionId());

    for (let file of acceptedFiles) {
      const formData = new FormData();
      formData.append("files", file);
      const response: FileResponse[] = await uploadFile(formData, null);

      if (response.length > 0) {
        const uploadedFile = response[0];

        if (intent == UploadIntent.ADD_TO_DOCUMENTS) {
          addSelectedFile(uploadedFile);
        } else {
          const newFileDescriptor: FileDescriptor = {
            // Use file_id (storage ID) if available, otherwise fallback to DB id
            // Ensure it's a string as FileDescriptor expects
            id: uploadedFile.file_id
              ? String(uploadedFile.file_id)
              : String(uploadedFile.id),
            type: uploadedFile.chat_file_type
              ? uploadedFile.chat_file_type
              : ChatFileType.PLAIN_TEXT,
            name: uploadedFile.name,
            isUploading: false, // Mark as successfully uploaded
          };

          setCurrentMessageFiles((prev) => [...prev, newFileDescriptor]);
        }
      } else {
        setPopup({
          type: "error",
          message: "Failed to upload file",
        });
      }
    }

    updateChatState("input", currentSessionId());
  };

  const messageHistory = useMemo(() => {
    return getLatestMessageChain(currentMessageMap(completeMessageDetail));
  }, [completeMessageDetail]);

  const onMessageSelection = (messageId: number) => {
    setSelectedMessageForDocDisplay(messageId);
    const newMessageTree = setMessageAsLatest(
      currentMessageMap(completeMessageDetail),
      messageId
    );
    updateCompleteMessageDetail(currentSessionId(), newMessageTree);

    // makes actual API call to set message as latest in the DB so we can
    // edit this message and so it sticks around on page reload
    patchMessageToBeLatest(messageId);
  };

  // fetch chat messages for the chat session
  useEffect(() => {
    const priorChatSessionId = chatSessionIdRef.current;
    const loadedSessionId = loadedIdSessionRef.current;
    chatSessionIdRef.current = existingChatSessionId;
    loadedIdSessionRef.current = existingChatSessionId;

    textAreaRef.current?.focus();

    // only clear things if we're going from one chat session to another
    const isChatSessionSwitch = existingChatSessionId !== priorChatSessionId;
    if (isChatSessionSwitch) {
      // de-select documents

      // reset all filters
      filterManager.setSelectedDocumentSets([]);
      filterManager.setSelectedSources([]);
      filterManager.setSelectedTags([]);
      filterManager.setTimeRange(null);

      // remove uploaded files
      setCurrentMessageFiles([]);

      // if switching from one chat to another, then need to scroll again
      // if we're creating a brand new chat, then don't need to scroll
      if (priorChatSessionId !== null) {
        setSelectedDocuments([]);
        clearSelectedItems();
        setHasPerformedInitialScroll(false);
      }
    }

    async function initialSessionFetch() {
      if (existingChatSessionId === null) {
        // reset the selected assistant back to default
        setSelectedAssistantFromId(null);
        updateCompleteMessageDetail(null, new Map());
        setChatSessionSharedStatus(ChatSessionSharedStatus.Private);

        // if we're supposed to submit on initial load, then do that here
        if (
          shouldSubmitOnLoad(searchParams) &&
          !submitOnLoadPerformed.current
        ) {
          submitOnLoadPerformed.current = true;
          await onSubmit({
            message: firstMessage || "",
            selectedFiles: [],
            selectedFolders: [],
            currentMessageFiles: [],
            useLanggraph: false,
          });
        }
        return;
      }

      const response = await fetch(
        `/api/chat/get-chat-session/${existingChatSessionId}`
      );

      const session = await response.json();
      const chatSession = session as BackendChatSession;
      setSelectedAssistantFromId(chatSession.persona_id);

      const newMessageMap = processRawChatHistory(chatSession.messages);
      const newMessageHistory = getLatestMessageChain(newMessageMap);

      // Update message history except for edge where where
      // last message is an error and we're on a new chat.
      // This corresponds to a "renaming" of chat, which occurs after first message
      // stream
      if (
        (newMessageHistory[newMessageHistory.length - 1]?.type !== "error" ||
          loadedSessionId != null) &&
        !(
          currentChatState() == "toolBuilding" ||
          currentChatState() == "streaming" ||
          currentChatState() == "loading"
        )
      ) {
        const latestMessageId =
          newMessageHistory[newMessageHistory.length - 1]?.messageId;

        setSelectedMessageForDocDisplay(
          latestMessageId !== undefined && latestMessageId !== null
            ? latestMessageId
            : null
        );

        updateCompleteMessageDetail(chatSession.chat_session_id, newMessageMap);
      }

      // go to bottom. If initial load, then do a scroll,
      // otherwise just appear at the bottom
      scrollInitialized.current = false;

      if (!hasPerformedInitialScroll) {
        if (isInitialLoad.current) {
          setHasPerformedInitialScroll(true);
          isInitialLoad.current = false;
        }
        clientScrollToBottom();

        setTimeout(() => {
          setHasPerformedInitialScroll(true);
        }, 100);
      } else if (isChatSessionSwitch) {
        setHasPerformedInitialScroll(true);
        clientScrollToBottom(true);
      }

      setIsFetchingChatMessages(false);

      // if this is a seeded chat, then kick off the AI message generation
      if (
        newMessageHistory.length === 1 &&
        !submitOnLoadPerformed.current &&
        searchParams?.get(SEARCH_PARAM_NAMES.SEEDED) === "true"
      ) {
        submitOnLoadPerformed.current = true;
        const seededMessage = newMessageHistory[0].message;
        await onSubmit({
          message: seededMessage,
          isSeededChat: true,
          selectedFiles: [],
          selectedFolders: [],
          currentMessageFiles: [],
          useLanggraph: false,
        });
        // force re-name if the chat session doesn't have one
        if (!chatSession.description) {
          await nameChatSession(existingChatSessionId);
          refreshChatSessions();
        }
      } else if (newMessageHistory.length === 2 && !chatSession.description) {
        await nameChatSession(existingChatSessionId);
        refreshChatSessions();
      }
    }

    initialSessionFetch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [existingChatSessionId, searchParams?.get(SEARCH_PARAM_NAMES.PERSONA_ID)]);

  useEffect(() => {
    return () => {
      // Cleanup which only runs when the component unmounts (i.e. when you navigate away).
      const currentSession = currentSessionId();
      const controller = abortControllersRef.current.get(currentSession);
      if (controller) {
        controller.abort();
        navigatingAway.current = true;
        setAbortControllers((prev) => {
          const newControllers = new Map(prev);
          newControllers.delete(currentSession);
          return newControllers;
        });
      }
    };
  }, [pathname]);

  // update chosen assistant if we navigate between pages
  useEffect(() => {
    if (messageHistory.length === 0 && chatSessionIdRef.current === null) {
      // Select from available assistants so shared assistants appear.
      setSelectedAssistantFromId(null);
    }
  }, [chatSessionIdRef.current, availableAssistants, messageHistory.length]);

  useEffect(() => {
    const handleSlackChatRedirect = async () => {
      const slackChatId = searchParams.get("slackChatId");
      if (!slackChatId) return;

      // Set isReady to false before starting retrieval to display loading text
      setIsReady(false);

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

  // fetch # of document tokens for the selected files
  useEffect(() => {
    const calculateTokensAndUpdateSearchMode = async () => {
      if (selectedFiles.length > 0 || selectedFolders.length > 0) {
        try {
          // Prepare the query parameters for the API call
          const fileIds = selectedFiles.map((file: FileResponse) => file.id);
          const folderIds = selectedFolders.map(
            (folder: FolderResponse) => folder.id
          );

          // Build the query string
          const queryParams = new URLSearchParams();
          fileIds.forEach((id) =>
            queryParams.append("file_ids", id.toString())
          );
          folderIds.forEach((id) =>
            queryParams.append("folder_ids", id.toString())
          );

          // Make the API call to get token estimate
          const response = await fetch(
            `/api/user/file/token-estimate?${queryParams.toString()}`
          );

          if (!response.ok) {
            console.error("Failed to fetch token estimate");
            return;
          }
        } catch (error) {
          console.error("Error calculating tokens:", error);
        }
      }
    };

    calculateTokensAndUpdateSearchMode();
  }, [selectedFiles, selectedFolders, llmManager.currentLlm]);

  // check if there's an image file in the message history so that we know
  // which LLMs are available to use
  const imageFileInMessageHistory = useMemo(() => {
    return messageHistory
      .filter((message) => message.type === "user")
      .some((message) =>
        message.files.some((file) => file.type === ChatFileType.IMAGE)
      );
  }, [messageHistory]);

  useEffect(() => {
    llmManager.updateImageFilesPresent(imageFileInMessageHistory);
  }, [imageFileInMessageHistory]);

  // highlight code blocks and set isReady once that's done
  useEffect(() => {
    Prism.highlightAll();
    setIsReady(true);
  }, []);

  return {
    // actions
    onSubmit,
    stopGenerating,
    onMessageSelection,
    handleImageUpload,

    // overall state
    completeMessageDetail,
    abortControllers,
    isReady,
    maxTokens,
    isFetchingChatMessages,

    // current state
    currentChatState: currentChatState(),
    currentRegenerationState: regenerationState.get(currentSessionId()),
    chatSessionId: currentSessionId(),
    submittedMessage,
    canContinue,
    agenticGenerating,
    uncaughtError,
    loadingError,
  };
}
