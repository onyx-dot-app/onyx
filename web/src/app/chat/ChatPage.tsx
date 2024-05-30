"use client";

import { useRouter, useSearchParams } from "next/navigation";
import {
  BackendChatSession,
  BackendMessage,
  ChatFileType,
  ChatSessionSharedStatus,
  DocumentsResponse,
  FileDescriptor,
  ImageGenerationDisplay,
  Message,
  RetrievalType,
  StreamingError,
  ToolRunKickoff,
} from "./interfaces";
import { ChatSidebar } from "./sessionSidebar/ChatSidebar";
import { Persona } from "../admin/assistants/interfaces";
import { Footer } from "@/components/Footer";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import { InstantSSRAutoRefresh } from "@/components/SSRAutoRefresh";
import {
  buildChatUrl,
  buildLatestMessageChain,
  createChatSession,
  getCitedDocumentsFromMessage,
  getHumanAndAIMessageFromMessageNumber,
  getLastSuccessfulMessageId,
  handleAutoScroll,
  handleChatFeedback,
  nameChatSession,
  personaIncludesRetrieval,
  processRawChatHistory,
  removeMessage,
  sendMessage,
  setMessageAsLatest,
  updateParentChildren,
  uploadFilesForChat,
} from "./lib";
import { useContext, useEffect, useRef, useState } from "react";
import { usePopup } from "@/components/admin/connectors/Popup";
import { SEARCH_PARAM_NAMES, shouldSubmitOnLoad } from "./searchParams";
import { useDocumentSelection } from "./useDocumentSelection";
import { useFilters, useLlmOverride } from "@/lib/hooks";
import { computeAvailableFilters } from "@/lib/filters";
import { FeedbackType } from "./types";
import ResizableSection from "@/components/resizable/ResizableSection";
import { DocumentSidebar } from "./documentSidebar/DocumentSidebar";
import { DanswerInitializingLoader } from "@/components/DanswerInitializingLoader";
import { FeedbackModal } from "./modal/FeedbackModal";
import { ShareChatSessionModal } from "./modal/ShareChatSessionModal";
import { ChatPersonaSelector } from "./ChatPersonaSelector";
import { FiShare2 } from "react-icons/fi";
import { ChatIntro } from "./ChatIntro";
import { AIMessage, HumanMessage } from "./message/Messages";
import { ThreeDots } from "react-loader-spinner";
import { StarterMessage } from "./StarterMessage";
import { AnswerPiecePacket, DanswerDocument } from "@/lib/search/interfaces";
import { buildFilters } from "@/lib/search/utils";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import Dropzone from "react-dropzone";
import { checkLLMSupportsImageInput, getFinalLLM } from "@/lib/llm/utils";
import { ChatInputBar } from "./input/ChatInputBar";
import { ConfigurationModal } from "./modal/configuration/ConfigurationModal";
import { useChatContext } from "@/components/context/ChatContext";
import { UserDropdown } from "@/components/UserDropdown";
import { v4 as uuidv4 } from "uuid";
import { orderAssistantsForUser } from "@/lib/assistants/orderAssistants";

const MAX_INPUT_HEIGHT = 200;
const TEMP_USER_MESSAGE_ID = -1;
const TEMP_ASSISTANT_MESSAGE_ID = -2;
const SYSTEM_MESSAGE_ID = -3;

export function ChatPage({
  documentSidebarInitialWidth,
  defaultSelectedPersonaId,
  footerHtml,
}: {
  documentSidebarInitialWidth?: number;
  defaultSelectedPersonaId?: number;
  footerHtml?: any;
}) {
  const [configModalActiveTab, setConfigModalActiveTab] = useState<
    string | null
  >(null);
  let {
    user,
    chatSessions,
    availableSources,
    availableDocumentSets,
    availablePersonas,
    llmProviders,
    folders,
    openedFolders,
  } = useChatContext();
  const filteredAssistants = orderAssistantsForUser(availablePersonas, user);

  const router = useRouter();
  const searchParams = useSearchParams();
  const existingChatIdRaw = searchParams.get("chatId");
  const existingChatSessionId = existingChatIdRaw
    ? parseInt(existingChatIdRaw)
    : null;

  const selectedChatSession = chatSessions.find(
    (chatSession) => chatSession.id === existingChatSessionId
  );
  const existingChatSessionPersonaId = selectedChatSession?.persona_id;

  // used to track whether or not the initial "submit on load" has been performed
  // this only applies if `?submit-on-load=true` or `?submit-on-load=1` is in the URL
  // NOTE: this is required due to React strict mode, where all `useEffect` hooks
  // are run twice on initial load during development
  const submitOnLoadPerformed = useRef<boolean>(false);

  const { popup, setPopup } = usePopup();

  // fetch messages for the chat session
  const [isFetchingChatMessages, setIsFetchingChatMessages] = useState(
    existingChatSessionId !== null
  );

  // needed so closures (e.g. onSubmit) can access the current value
  const urlChatSessionId = useRef<number | null>();
  // this is triggered every time the user switches which chat
  // session they are using
  useEffect(() => {
    urlChatSessionId.current = existingChatSessionId;

    textAreaRef.current?.focus();

    // only clear things if we're going from one chat session to another
    if (chatSessionId !== null && existingChatSessionId !== chatSessionId) {
      // de-select documents
      clearSelectedDocuments();
      // reset all filters
      filterManager.setSelectedDocumentSets([]);
      filterManager.setSelectedSources([]);
      filterManager.setSelectedTags([]);
      filterManager.setTimeRange(null);
      // reset LLM overrides
      llmOverrideManager.setLlmOverride({
        name: "",
        provider: "",
        modelName: "",
      });
      llmOverrideManager.setTemperature(null);
      // remove uploaded files
      setCurrentMessageFiles([]);

      if (isStreaming) {
        setIsCancelled(true);
      }
    }

    setChatSessionId(existingChatSessionId);

    async function initialSessionFetch() {
      if (existingChatSessionId === null) {
        setIsFetchingChatMessages(false);
        if (defaultSelectedPersonaId !== undefined) {
          setSelectedPersona(
            filteredAssistants.find(
              (persona) => persona.id === defaultSelectedPersonaId
            )
          );
        } else {
          setSelectedPersona(undefined);
        }
        setCompleteMessageMap(new Map());
        setChatSessionSharedStatus(ChatSessionSharedStatus.Private);

        // if we're supposed to submit on initial load, then do that here
        if (
          shouldSubmitOnLoad(searchParams) &&
          !submitOnLoadPerformed.current
        ) {
          submitOnLoadPerformed.current = true;
          await onSubmit();
        }

        return;
      }

      setIsFetchingChatMessages(true);
      const response = await fetch(
        `/api/chat/get-chat-session/${existingChatSessionId}`
      );
      const chatSession = (await response.json()) as BackendChatSession;
      setSelectedPersona(
        filteredAssistants.find(
          (persona) => persona.id === chatSession.persona_id
        )
      );

      const newCompleteMessageMap = processRawChatHistory(chatSession.messages);
      const newMessageHistory = buildLatestMessageChain(newCompleteMessageMap);
      // if the last message is an error, don't overwrite it
      if (messageHistory[messageHistory.length - 1]?.type !== "error") {
        setCompleteMessageMap(newCompleteMessageMap);

        const latestMessageId =
          newMessageHistory[newMessageHistory.length - 1]?.messageId;
        setSelectedMessageForDocDisplay(
          latestMessageId !== undefined ? latestMessageId : null
        );
      }

      setChatSessionSharedStatus(chatSession.shared_status);

      setIsFetchingChatMessages(false);

      // if this is a seeded chat, then kick off the AI message generation
      if (
        newMessageHistory.length === 1 &&
        !submitOnLoadPerformed.current &&
        searchParams.get(SEARCH_PARAM_NAMES.SEEDED) === "true"
      ) {
        submitOnLoadPerformed.current = true;
        const seededMessage = newMessageHistory[0].message;
        await onSubmit({
          isSeededChat: true,
          messageOverride: seededMessage,
        });
        // force re-name if the chat session doesn't have one
        if (!chatSession.description) {
          await nameChatSession(existingChatSessionId, seededMessage);
          router.refresh(); // need to refresh to update name on sidebar
        }
      }
    }

    initialSessionFetch();
  }, [existingChatSessionId]);

  const [chatSessionId, setChatSessionId] = useState<number | null>(
    existingChatSessionId
  );
  const [message, setMessage] = useState(
    searchParams.get(SEARCH_PARAM_NAMES.USER_MESSAGE) || ""
  );
  const [completeMessageMap, setCompleteMessageMap] = useState<
    Map<number, Message>
  >(new Map());
  const upsertToCompleteMessageMap = ({
    messages,
    completeMessageMapOverride,
    replacementsMap = null,
    makeLatestChildMessage = false,
  }: {
    messages: Message[];
    // if calling this function repeatedly with short delay, stay may not update in time
    // and result in weird behavipr
    completeMessageMapOverride?: Map<number, Message> | null;
    replacementsMap?: Map<number, number> | null;
    makeLatestChildMessage?: boolean;
  }) => {
    // deep copy
    const frozenCompleteMessageMap =
      completeMessageMapOverride || completeMessageMap;
    const newCompleteMessageMap = structuredClone(frozenCompleteMessageMap);
    if (newCompleteMessageMap.size === 0) {
      const systemMessageId = messages[0].parentMessageId || SYSTEM_MESSAGE_ID;
      const firstMessageId = messages[0].messageId;
      const dummySystemMessage: Message = {
        messageId: systemMessageId,
        message: "",
        type: "system",
        files: [],
        parentMessageId: null,
        childrenMessageIds: [firstMessageId],
        latestChildMessageId: firstMessageId,
      };
      newCompleteMessageMap.set(
        dummySystemMessage.messageId,
        dummySystemMessage
      );
      messages[0].parentMessageId = systemMessageId;
    }
    messages.forEach((message) => {
      const idToReplace = replacementsMap?.get(message.messageId);
      if (idToReplace) {
        removeMessage(idToReplace, newCompleteMessageMap);
      }

      // update childrenMessageIds for the parent
      if (
        !newCompleteMessageMap.has(message.messageId) &&
        message.parentMessageId !== null
      ) {
        updateParentChildren(message, newCompleteMessageMap, true);
      }
      newCompleteMessageMap.set(message.messageId, message);
    });

    // if specified, make these new message the latest of the current message chain
    if (makeLatestChildMessage) {
      const currentMessageChain = buildLatestMessageChain(
        frozenCompleteMessageMap
      );
      const latestMessage = currentMessageChain[currentMessageChain.length - 1];
      if (latestMessage) {
        newCompleteMessageMap.get(
          latestMessage.messageId
        )!.latestChildMessageId = messages[0].messageId;
      }
    }
    setCompleteMessageMap(newCompleteMessageMap);
    return newCompleteMessageMap;
  };
  const messageHistory = buildLatestMessageChain(completeMessageMap);
  const [currentTool, setCurrentTool] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);

  // uploaded files
  const [currentMessageFiles, setCurrentMessageFiles] = useState<
    FileDescriptor[]
  >([]);

  // for document display
  // NOTE: -1 is a special designation that means the latest AI message
  const [selectedMessageForDocDisplay, setSelectedMessageForDocDisplay] =
    useState<number | null>(null);
  const { aiMessage } = selectedMessageForDocDisplay
    ? getHumanAndAIMessageFromMessageNumber(
        messageHistory,
        selectedMessageForDocDisplay
      )
    : { aiMessage: null };

  const [selectedPersona, setSelectedPersona] = useState<Persona | undefined>(
    existingChatSessionPersonaId !== undefined
      ? filteredAssistants.find(
          (persona) => persona.id === existingChatSessionPersonaId
        )
      : defaultSelectedPersonaId !== undefined
        ? filteredAssistants.find(
            (persona) => persona.id === defaultSelectedPersonaId
          )
        : undefined
  );
  const livePersona = selectedPersona || filteredAssistants[0];

  const [chatSessionSharedStatus, setChatSessionSharedStatus] =
    useState<ChatSessionSharedStatus>(ChatSessionSharedStatus.Private);

  useEffect(() => {
    if (messageHistory.length === 0 && chatSessionId === null) {
      setSelectedPersona(
        filteredAssistants.find(
          (persona) => persona.id === defaultSelectedPersonaId
        )
      );
    }
  }, [defaultSelectedPersonaId]);

  const [
    selectedDocuments,
    toggleDocumentSelection,
    clearSelectedDocuments,
    selectedDocumentTokens,
  ] = useDocumentSelection();
  // just choose a conservative default, this will be updated in the
  // background on initial load / on persona change
  const [maxTokens, setMaxTokens] = useState<number>(4096);
  // fetch # of allowed document tokens for the selected Persona
  useEffect(() => {
    async function fetchMaxTokens() {
      const response = await fetch(
        `/api/chat/max-selected-document-tokens?persona_id=${livePersona.id}`
      );
      if (response.ok) {
        const maxTokens = (await response.json()).max_tokens as number;
        setMaxTokens(maxTokens);
      }
    }

    fetchMaxTokens();
  }, [livePersona]);

  const filterManager = useFilters();
  const [finalAvailableSources, finalAvailableDocumentSets] =
    computeAvailableFilters({
      selectedPersona,
      availableSources,
      availableDocumentSets,
    });

  const llmOverrideManager = useLlmOverride();

  // state for cancelling streaming
  const [isCancelled, setIsCancelled] = useState(false);
  const isCancelledRef = useRef(isCancelled);
  useEffect(() => {
    isCancelledRef.current = isCancelled;
  }, [isCancelled]);

  const [currentFeedback, setCurrentFeedback] = useState<
    [FeedbackType, number] | null
  >(null);
  const [sharingModalVisible, setSharingModalVisible] =
    useState<boolean>(false);

  // auto scroll as message comes out
  const scrollableDivRef = useRef<HTMLDivElement>(null);
  const endDivRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (isStreaming || !message) {
      handleAutoScroll(endDivRef, scrollableDivRef);
    }
  });

  // scroll to bottom initially
  const [hasPerformedInitialScroll, setHasPerformedInitialScroll] =
    useState(false);
  useEffect(() => {
    endDivRef.current?.scrollIntoView();
    setHasPerformedInitialScroll(true);
  }, [isFetchingChatMessages]);

  // handle re-sizing of the text area
  const textAreaRef = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const textarea = textAreaRef.current;
    if (textarea) {
      textarea.style.height = "0px";
      textarea.style.height = `${Math.min(
        textarea.scrollHeight,
        MAX_INPUT_HEIGHT
      )}px`;
    }
  }, [message]);

  // used for resizing of the document sidebar
  const masterFlexboxRef = useRef<HTMLDivElement>(null);
  const [maxDocumentSidebarWidth, setMaxDocumentSidebarWidth] = useState<
    number | null
  >(null);
  const adjustDocumentSidebarWidth = () => {
    if (masterFlexboxRef.current && document.documentElement.clientWidth) {
      // numbers below are based on the actual width the center section for different
      // screen sizes. `1700` corresponds to the custom "3xl" tailwind breakpoint
      // NOTE: some buffer is needed to account for scroll bars
      if (document.documentElement.clientWidth > 1700) {
        setMaxDocumentSidebarWidth(masterFlexboxRef.current.clientWidth - 950);
      } else if (document.documentElement.clientWidth > 1420) {
        setMaxDocumentSidebarWidth(masterFlexboxRef.current.clientWidth - 760);
      } else {
        setMaxDocumentSidebarWidth(masterFlexboxRef.current.clientWidth - 660);
      }
    }
  };
  useEffect(() => {
    adjustDocumentSidebarWidth(); // Adjust the width on initial render
    window.addEventListener("resize", adjustDocumentSidebarWidth); // Add resize event listener

    return () => {
      window.removeEventListener("resize", adjustDocumentSidebarWidth); // Cleanup the event listener
    };
  }, []);

  if (!documentSidebarInitialWidth && maxDocumentSidebarWidth) {
    documentSidebarInitialWidth = Math.min(700, maxDocumentSidebarWidth);
  }

  const onSubmit = async ({
    messageIdToResend,
    messageOverride,
    queryOverride,
    forceSearch,
    isSeededChat,
  }: {
    messageIdToResend?: number;
    messageOverride?: string;
    queryOverride?: string;
    forceSearch?: boolean;
    isSeededChat?: boolean;
  } = {}) => {
    let currChatSessionId: number;
    let isNewSession = chatSessionId === null;
    const searchParamBasedChatSessionName =
      searchParams.get(SEARCH_PARAM_NAMES.TITLE) || null;

    if (isNewSession) {
      currChatSessionId = await createChatSession(
        livePersona?.id || 0,
        searchParamBasedChatSessionName
      );
    } else {
      currChatSessionId = chatSessionId as number;
    }
    setChatSessionId(currChatSessionId);

    const messageToResend = messageHistory.find(
      (message) => message.messageId === messageIdToResend
    );
    const messageToResendParent =
      messageToResend?.parentMessageId !== null &&
      messageToResend?.parentMessageId !== undefined
        ? completeMessageMap.get(messageToResend.parentMessageId)
        : null;
    const messageToResendIndex = messageToResend
      ? messageHistory.indexOf(messageToResend)
      : null;
    if (!messageToResend && messageIdToResend !== undefined) {
      setPopup({
        message:
          "Failed to re-send message - please refresh the page and try again.",
        type: "error",
      });
      return;
    }

    let currMessage = messageToResend ? messageToResend.message : message;
    if (messageOverride) {
      currMessage = messageOverride;
    }
    const currMessageHistory =
      messageToResendIndex !== null
        ? messageHistory.slice(0, messageToResendIndex)
        : messageHistory;
    let parentMessage =
      messageToResendParent ||
      (currMessageHistory.length > 0
        ? currMessageHistory[currMessageHistory.length - 1]
        : null);

    // if we're resending, set the parent's child to null
    // we will use tempMessages until the regenerated message is complete
    const messageUpdates: Message[] = [
      {
        messageId: TEMP_USER_MESSAGE_ID,
        message: currMessage,
        type: "user",
        files: currentMessageFiles,
        parentMessageId: parentMessage?.messageId || null,
      },
    ];
    if (parentMessage) {
      messageUpdates.push({
        ...parentMessage,
        childrenMessageIds: (parentMessage.childrenMessageIds || []).concat([
          TEMP_USER_MESSAGE_ID,
        ]),
        latestChildMessageId: TEMP_USER_MESSAGE_ID,
      });
    }
    const frozenCompleteMessageMap = upsertToCompleteMessageMap({
      messages: messageUpdates,
    });
    // on initial message send, we insert a dummy system message
    // set this as the parent here if no parent is set
    if (!parentMessage && frozenCompleteMessageMap.size === 2) {
      parentMessage = frozenCompleteMessageMap.get(SYSTEM_MESSAGE_ID) || null;
    }
    setMessage("");
    setCurrentMessageFiles([]);

    setIsStreaming(true);
    let answer = "";
    let query: string | null = null;
    let retrievalType: RetrievalType =
      selectedDocuments.length > 0
        ? RetrievalType.SelectedDocs
        : RetrievalType.None;
    let documents: DanswerDocument[] = selectedDocuments;
    let aiMessageImages: FileDescriptor[] | null = null;
    let error: string | null = null;
    let finalMessage: BackendMessage | null = null;
    try {
      const lastSuccessfulMessageId =
        getLastSuccessfulMessageId(currMessageHistory);
      for await (const packetBunch of sendMessage({
        message: currMessage,
        fileDescriptors: currentMessageFiles,
        parentMessageId: lastSuccessfulMessageId,
        chatSessionId: currChatSessionId,
        promptId: livePersona?.prompts[0]?.id || 0,
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
        modelProvider: llmOverrideManager.llmOverride.name || undefined,
        modelVersion:
          llmOverrideManager.llmOverride.modelName ||
          searchParams.get(SEARCH_PARAM_NAMES.MODEL_VERSION) ||
          undefined,
        temperature:
          llmOverrideManager.temperature ||
          parseFloat(searchParams.get(SEARCH_PARAM_NAMES.TEMPERATURE) || "") ||
          undefined,
        systemPromptOverride:
          searchParams.get(SEARCH_PARAM_NAMES.SYSTEM_PROMPT) || undefined,
        useExistingUserMessage: isSeededChat,
      })) {
        for (const packet of packetBunch) {
          if (Object.hasOwn(packet, "answer_piece")) {
            answer += (packet as AnswerPiecePacket).answer_piece;
          } else if (Object.hasOwn(packet, "top_documents")) {
            documents = (packet as DocumentsResponse).top_documents;
            query = (packet as DocumentsResponse).rephrased_query;
            retrievalType = RetrievalType.Search;
            if (documents && documents.length > 0) {
              // point to the latest message (we don't know the messageId yet, which is why
              // we have to use -1)
              setSelectedMessageForDocDisplay(TEMP_USER_MESSAGE_ID);
            }
          } else if (Object.hasOwn(packet, "file_ids")) {
            aiMessageImages = (packet as ImageGenerationDisplay).file_ids.map(
              (fileId) => {
                return {
                  id: fileId,
                  type: ChatFileType.IMAGE,
                };
              }
            );
          } else if (Object.hasOwn(packet, "tool_name")) {
            setCurrentTool((packet as ToolRunKickoff).tool_name);
          } else if (Object.hasOwn(packet, "error")) {
            error = (packet as StreamingError).error;
          } else if (Object.hasOwn(packet, "message_id")) {
            finalMessage = packet as BackendMessage;
          }
        }
        const updateFn = (messages: Message[]) => {
          const replacementsMap = finalMessage
            ? new Map([
                [messages[0].messageId, TEMP_USER_MESSAGE_ID],
                [messages[1].messageId, TEMP_ASSISTANT_MESSAGE_ID],
              ] as [number, number][])
            : null;
          upsertToCompleteMessageMap({
            messages: messages,
            replacementsMap: replacementsMap,
            completeMessageMapOverride: frozenCompleteMessageMap,
          });
        };
        const newUserMessageId =
          finalMessage?.parent_message || TEMP_USER_MESSAGE_ID;
        const newAssistantMessageId =
          finalMessage?.message_id || TEMP_ASSISTANT_MESSAGE_ID;
        updateFn([
          {
            messageId: newUserMessageId,
            message: currMessage,
            type: "user",
            files: currentMessageFiles,
            parentMessageId: parentMessage?.messageId || null,
            childrenMessageIds: [newAssistantMessageId],
            latestChildMessageId: newAssistantMessageId,
          },
          {
            messageId: newAssistantMessageId,
            message: error || answer,
            type: error ? "error" : "assistant",
            retrievalType,
            query: finalMessage?.rephrased_query || query,
            documents: finalMessage?.context_docs?.top_documents || documents,
            citations: finalMessage?.citations || {},
            files: finalMessage?.files || aiMessageImages || [],
            parentMessageId: newUserMessageId,
          },
        ]);
        if (isCancelledRef.current) {
          setIsCancelled(false);
          break;
        }
      }
    } catch (e: any) {
      const errorMsg = e.message;
      upsertToCompleteMessageMap({
        messages: [
          {
            messageId: TEMP_USER_MESSAGE_ID,
            message: currMessage,
            type: "user",
            files: currentMessageFiles,
            parentMessageId: null,
          },
          {
            messageId: TEMP_ASSISTANT_MESSAGE_ID,
            message: errorMsg,
            type: "error",
            files: aiMessageImages || [],
            parentMessageId: null,
          },
        ],
        completeMessageMapOverride: frozenCompleteMessageMap,
      });
    }
    setIsStreaming(false);
    if (isNewSession) {
      if (finalMessage) {
        setSelectedMessageForDocDisplay(finalMessage.message_id);
      }
      if (!searchParamBasedChatSessionName) {
        await nameChatSession(currChatSessionId, currMessage);
      }

      // NOTE: don't switch pages if the user has navigated away from the chat
      if (
        currChatSessionId === urlChatSessionId.current ||
        urlChatSessionId.current === null
      ) {
        router.push(buildChatUrl(searchParams, currChatSessionId, null), {
          scroll: false,
        });
      }
    }
    if (
      finalMessage?.context_docs &&
      finalMessage.context_docs.top_documents.length > 0 &&
      retrievalType === RetrievalType.Search
    ) {
      setSelectedMessageForDocDisplay(finalMessage.message_id);
    }
  };

  const onFeedback = async (
    messageId: number,
    feedbackType: FeedbackType,
    feedbackDetails: string,
    predefinedFeedback: string | undefined
  ) => {
    if (chatSessionId === null) {
      return;
    }

    const response = await handleChatFeedback(
      messageId,
      feedbackType,
      feedbackDetails,
      predefinedFeedback
    );

    if (response.ok) {
      setPopup({
        message: "Thanks for your feedback!",
        type: "success",
      });
    } else {
      const responseJson = await response.json();
      const errorMsg = responseJson.detail || responseJson.message;
      setPopup({
        message: `Failed to submit feedback - ${errorMsg}`,
        type: "error",
      });
    }
  };

  const onPersonaChange = (persona: Persona | null) => {
    if (persona && persona.id !== livePersona.id) {
      // remove uploaded files
      setCurrentMessageFiles([]);

      setSelectedPersona(persona);
      textAreaRef.current?.focus();
      router.push(buildChatUrl(searchParams, null, persona.id));
    }
  };

  const handleImageUpload = (acceptedFiles: File[]) => {
    const llmAcceptsImages = checkLLMSupportsImageInput(
      ...getFinalLLM(llmProviders, livePersona)
    );
    const imageFiles = acceptedFiles.filter((file) =>
      file.type.startsWith("image/")
    );
    if (imageFiles.length > 0 && !llmAcceptsImages) {
      setPopup({
        type: "error",
        message:
          "The current Assistant does not support image input. Please select an assistant with Vision support.",
      });
      return;
    }

    const tempFileDescriptors = acceptedFiles.map((file) => ({
      id: uuidv4(),
      type: file.type.startsWith("image/")
        ? ChatFileType.IMAGE
        : ChatFileType.DOCUMENT,
      isUploading: true,
    }));

    // only show loading spinner for reasonably large files
    const totalSize = acceptedFiles.reduce((sum, file) => sum + file.size, 0);
    if (totalSize > 50 * 1024) {
      setCurrentMessageFiles((prev) => [...prev, ...tempFileDescriptors]);
    }

    const removeTempFiles = (prev: FileDescriptor[]) => {
      return prev.filter(
        (file) => !tempFileDescriptors.some((newFile) => newFile.id === file.id)
      );
    };

    uploadFilesForChat(acceptedFiles).then(([files, error]) => {
      if (error) {
        setCurrentMessageFiles((prev) => removeTempFiles(prev));
        setPopup({
          type: "error",
          message: error,
        });
      } else {
        setCurrentMessageFiles((prev) => [...removeTempFiles(prev), ...files]);
      }
    });
  };

  // handle redirect if chat page is disabled
  // NOTE: this must be done here, in a client component since
  // settings are passed in via Context and therefore aren't
  // available in server-side components
  const settings = useContext(SettingsContext);
  if (settings?.settings?.chat_page_enabled === false) {
    router.push("/search");
  }

  const retrievalDisabled = !personaIncludesRetrieval(livePersona);
  return (
    <>
      {/* <div className="absolute top-0 z-40 w-full">
        <Header user={user} />
      </div> */}
      <HealthCheckBanner />
      <InstantSSRAutoRefresh />

      <div className="flex relative bg-background text-default overflow-x-hidden">
        <ChatSidebar
          existingChats={chatSessions}
          currentChatSession={selectedChatSession}
          folders={folders}
          openedFolders={openedFolders}
        />
        <div className="flex w-full overflow-x-hidden" ref={masterFlexboxRef}>
          {popup}
          {currentFeedback && (
            <FeedbackModal
              feedbackType={currentFeedback[0]}
              onClose={() => setCurrentFeedback(null)}
              onSubmit={({ message, predefinedFeedback }) => {
                onFeedback(
                  currentFeedback[1],
                  currentFeedback[0],
                  message,
                  predefinedFeedback
                );
                setCurrentFeedback(null);
              }}
            />
          )}

          {sharingModalVisible && chatSessionId !== null && (
            <ShareChatSessionModal
              chatSessionId={chatSessionId}
              existingSharedStatus={chatSessionSharedStatus}
              onClose={() => setSharingModalVisible(false)}
              onShare={(shared) =>
                setChatSessionSharedStatus(
                  shared
                    ? ChatSessionSharedStatus.Public
                    : ChatSessionSharedStatus.Private
                )
              }
            />
          )}

          <ConfigurationModal
            activeTab={configModalActiveTab}
            setActiveTab={setConfigModalActiveTab}
            onClose={() => setConfigModalActiveTab(null)}
            filterManager={filterManager}
            selectedAssistant={livePersona}
            setSelectedAssistant={onPersonaChange}
            llmOverrideManager={llmOverrideManager}
          />

          {documentSidebarInitialWidth !== undefined ? (
            <Dropzone onDrop={handleImageUpload} noClick>
              {({ getRootProps }) => (
                <>
                  <div
                    className={`w-full sm:relative h-screen ${
                      retrievalDisabled ? "pb-[111px]" : "pb-[140px]"
                    }`}
                    {...getRootProps()}
                  >
                    {/* <input {...getInputProps()} /> */}
                    <div
                      className={`w-full h-full flex flex-col overflow-y-auto overflow-x-hidden relative`}
                      ref={scrollableDivRef}
                    >
                      {livePersona && (
                        <div className="sticky top-0 left-80 z-10 w-full bg-background flex">
                          <div className="mt-2 flex w-full">
                            <div className="ml-2 p-1 rounded w-fit">
                              <ChatPersonaSelector
                                personas={filteredAssistants}
                                selectedPersonaId={livePersona.id}
                                onPersonaChange={onPersonaChange}
                                userId={user?.id}
                              />
                            </div>

                            <div className="ml-auto mr-8 flex">
                              {chatSessionId !== null && (
                                <div
                                  onClick={() => setSharingModalVisible(true)}
                                  className={`
                                    my-auto
                                    p-2
                                    rounded
                                    cursor-pointer
                                    hover:bg-hover-light
                                  `}
                                >
                                  <FiShare2 size="18" />
                                </div>
                              )}

                              <div className="ml-4 my-auto">
                                <UserDropdown user={user} />
                              </div>
                            </div>
                          </div>
                        </div>
                      )}

                      {messageHistory.length === 0 &&
                        !isFetchingChatMessages &&
                        !isStreaming && (
                          <ChatIntro
                            availableSources={finalAvailableSources}
                            availablePersonas={filteredAssistants}
                            selectedPersona={livePersona}
                          />
                        )}

                      <div
                        className={
                          "mt-4 pt-12 sm:pt-0 mx-8" +
                          (hasPerformedInitialScroll ? "" : " invisible")
                        }
                      >
                        {messageHistory.map((message, i) => {
                          if (message.type === "user") {
                            const parentMessage = message.parentMessageId
                              ? completeMessageMap.get(message.parentMessageId)
                              : null;
                            return (
                              <div key={i}>
                                <HumanMessage
                                  content={message.message}
                                  files={message.files}
                                  messageId={message.messageId}
                                  otherMessagesCanSwitchTo={
                                    parentMessage?.childrenMessageIds || []
                                  }
                                  onEdit={(editedContent) => {
                                    const parentMessageId =
                                      message.parentMessageId!;
                                    const parentMessage =
                                      completeMessageMap.get(parentMessageId)!;
                                    upsertToCompleteMessageMap({
                                      messages: [
                                        {
                                          ...parentMessage,
                                          latestChildMessageId: null,
                                        },
                                      ],
                                    });
                                    onSubmit({
                                      messageIdToResend:
                                        message.messageId || undefined,
                                      messageOverride: editedContent,
                                    });
                                  }}
                                  onMessageSelection={(messageId) => {
                                    const newCompleteMessageMap = new Map(
                                      completeMessageMap
                                    );
                                    newCompleteMessageMap.get(
                                      message.parentMessageId!
                                    )!.latestChildMessageId = messageId;
                                    setCompleteMessageMap(
                                      newCompleteMessageMap
                                    );
                                    setSelectedMessageForDocDisplay(messageId);

                                    // set message as latest so we can edit this message
                                    // and so it sticks around on page reload
                                    setMessageAsLatest(messageId);
                                  }}
                                />
                              </div>
                            );
                          } else if (message.type === "assistant") {
                            const isShowingRetrieved =
                              (selectedMessageForDocDisplay !== null &&
                                selectedMessageForDocDisplay ===
                                  message.messageId) ||
                              (selectedMessageForDocDisplay ===
                                TEMP_USER_MESSAGE_ID &&
                                i === messageHistory.length - 1);
                            const previousMessage =
                              i !== 0 ? messageHistory[i - 1] : null;
                            return (
                              <AIMessage
                                key={message.messageId}
                                messageId={message.messageId}
                                content={message.message}
                                files={message.files}
                                query={messageHistory[i]?.query || undefined}
                                personaName={livePersona.name}
                                citedDocuments={getCitedDocumentsFromMessage(
                                  message
                                )}
                                currentTool={currentTool}
                                isComplete={
                                  i !== messageHistory.length - 1 ||
                                  !isStreaming
                                }
                                hasDocs={
                                  (message.documents &&
                                    message.documents.length > 0) === true
                                }
                                handleFeedback={
                                  i === messageHistory.length - 1 && isStreaming
                                    ? undefined
                                    : (feedbackType) =>
                                        setCurrentFeedback([
                                          feedbackType,
                                          message.messageId as number,
                                        ])
                                }
                                handleSearchQueryEdit={
                                  i === messageHistory.length - 1 &&
                                  !isStreaming
                                    ? (newQuery) => {
                                        if (!previousMessage) {
                                          setPopup({
                                            type: "error",
                                            message:
                                              "Cannot edit query of first message - please refresh the page and try again.",
                                          });
                                          return;
                                        }

                                        if (
                                          previousMessage.messageId === null
                                        ) {
                                          setPopup({
                                            type: "error",
                                            message:
                                              "Cannot edit query of a pending message - please wait a few seconds and try again.",
                                          });
                                          return;
                                        }
                                        onSubmit({
                                          messageIdToResend:
                                            previousMessage.messageId,
                                          queryOverride: newQuery,
                                        });
                                      }
                                    : undefined
                                }
                                isCurrentlyShowingRetrieved={isShowingRetrieved}
                                handleShowRetrieved={(messageNumber) => {
                                  if (isShowingRetrieved) {
                                    setSelectedMessageForDocDisplay(null);
                                  } else {
                                    if (messageNumber !== null) {
                                      setSelectedMessageForDocDisplay(
                                        messageNumber
                                      );
                                    } else {
                                      setSelectedMessageForDocDisplay(-1);
                                    }
                                  }
                                }}
                                handleForceSearch={() => {
                                  if (
                                    previousMessage &&
                                    previousMessage.messageId
                                  ) {
                                    onSubmit({
                                      messageIdToResend:
                                        previousMessage.messageId,
                                      forceSearch: true,
                                    });
                                  } else {
                                    setPopup({
                                      type: "error",
                                      message:
                                        "Failed to force search - please refresh the page and try again.",
                                    });
                                  }
                                }}
                                retrievalDisabled={retrievalDisabled}
                              />
                            );
                          } else {
                            return (
                              <div key={i}>
                                <AIMessage
                                  messageId={message.messageId}
                                  personaName={livePersona.name}
                                  content={
                                    <p className="text-red-700 text-sm my-auto">
                                      {message.message}
                                    </p>
                                  }
                                />
                              </div>
                            );
                          }
                        })}

                        {isStreaming &&
                          messageHistory.length > 0 &&
                          messageHistory[messageHistory.length - 1].type ===
                            "user" && (
                            <div key={messageHistory.length}>
                              <AIMessage
                                messageId={null}
                                personaName={livePersona.name}
                                content={
                                  <div className="text-sm my-auto">
                                    <ThreeDots
                                      height="30"
                                      width="50"
                                      color="#3b82f6"
                                      ariaLabel="grid-loading"
                                      radius="12.5"
                                      wrapperStyle={{}}
                                      wrapperClass=""
                                      visible={true}
                                    />
                                  </div>
                                }
                              />
                            </div>
                          )}

                        {/* Some padding at the bottom so the search bar has space at the bottom to not cover the last message*/}
                        <div className={`min-h-[100px] w-full`}></div>

                        {livePersona &&
                          livePersona.starter_messages &&
                          livePersona.starter_messages.length > 0 &&
                          selectedPersona &&
                          messageHistory.length === 0 &&
                          !isFetchingChatMessages && (
                            <div
                              className={`
                            mx-auto 
                            px-4 
                            w-searchbar-xs 
                            2xl:w-searchbar-sm 
                            3xl:w-searchbar 
                            grid 
                            gap-4 
                            grid-cols-1 
                            grid-rows-1 
                            mt-4 
                            md:grid-cols-2 
                            mb-6`}
                            >
                              {livePersona.starter_messages.map(
                                (starterMessage, i) => (
                                  <div key={i} className="w-full">
                                    <StarterMessage
                                      starterMessage={starterMessage}
                                      onClick={() =>
                                        onSubmit({
                                          messageOverride:
                                            starterMessage.message,
                                        })
                                      }
                                    />
                                  </div>
                                )
                              )}
                            </div>
                          )}

                        <div ref={endDivRef} />
                      </div>
                    </div>

                    <div className="absolute bottom-0 z-10 w-full">
                      <div className="w-full pb-4">
                        <ChatInputBar
                          message={message}
                          setMessage={setMessage}
                          onSubmit={onSubmit}
                          isStreaming={isStreaming}
                          setIsCancelled={setIsCancelled}
                          retrievalDisabled={retrievalDisabled}
                          filterManager={filterManager}
                          llmOverrideManager={llmOverrideManager}
                          selectedAssistant={livePersona}
                          files={currentMessageFiles}
                          setFiles={setCurrentMessageFiles}
                          handleFileUpload={handleImageUpload}
                          setConfigModalActiveTab={setConfigModalActiveTab}
                          textAreaRef={textAreaRef}
                        />
                      </div>
                    </div>
                  </div>

                  {!retrievalDisabled ? (
                    <ResizableSection
                      intialWidth={documentSidebarInitialWidth as number}
                      minWidth={400}
                      maxWidth={maxDocumentSidebarWidth || undefined}
                    >
                      <DocumentSidebar
                        selectedMessage={aiMessage}
                        selectedDocuments={selectedDocuments}
                        toggleDocumentSelection={toggleDocumentSelection}
                        clearSelectedDocuments={clearSelectedDocuments}
                        selectedDocumentTokens={selectedDocumentTokens}
                        maxTokens={maxTokens}
                        isLoading={isFetchingChatMessages}
                      />
                    </ResizableSection>
                  ) : // Another option is to use a div with the width set to the initial width, so that the
                  // chat section appears in the same place as before
                  // <div style={documentSidebarInitialWidth ? {width: documentSidebarInitialWidth} : {}}></div>
                  null}
                </>
              )}
            </Dropzone>
          ) : (
            <div className="mx-auto h-full flex flex-col">
              <div className="my-auto">
                <DanswerInitializingLoader />
              </div>
            </div>
          )}
        </div>
      </div>
      <Footer footerHtml={footerHtml}/>
    </>
  );
}
