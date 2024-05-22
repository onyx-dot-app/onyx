"use client";

import { useRouter, useSearchParams } from "next/navigation";
import {
  BackendChatSession,
  BackendMessage,
  ChatSession,
  ChatSessionSharedStatus,
  DocumentsResponse,
  FileDescriptor,
  Message,
  RetrievalType,
  StreamingError,
} from "./interfaces";
import { ChatSidebar } from "./sessionSidebar/ChatSidebar";
import { DocumentSet, Tag, User, ValidSources } from "@/lib/types";
import { Persona } from "../admin/assistants/interfaces";
import { Header } from "@/components/header/Header";
import { Footer } from "@/components/Footer";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import { InstantSSRAutoRefresh } from "@/components/SSRAutoRefresh";
import { Settings } from "../admin/settings/interfaces";
import {
  buildChatUrl,
  createChatSession,
  getCitedDocumentsFromMessage,
  getHumanAndAIMessageFromMessageNumber,
  getLastSuccessfulMessageId,
  handleAutoScroll,
  handleChatFeedback,
  nameChatSession,
  personaIncludesRetrieval,
  processRawChatHistory,
  sendMessage,
  uploadFilesForChat,
} from "./lib";
import { useContext, useEffect, useRef, useState } from "react";
import { usePopup } from "@/components/admin/connectors/Popup";
import { SEARCH_PARAM_NAMES, shouldSubmitOnLoad } from "./searchParams";
import { useDocumentSelection } from "./useDocumentSelection";
import { useFilters } from "@/lib/hooks";
import { computeAvailableFilters } from "@/lib/filters";
import { FeedbackType } from "./types";
import ResizableSection from "@/components/resizable/ResizableSection";
import { DocumentSidebar } from "./documentSidebar/DocumentSidebar";
import { DanswerInitializingLoader } from "@/components/DanswerInitializingLoader";
import { FeedbackModal } from "./modal/FeedbackModal";
import { ShareChatSessionModal } from "./modal/ShareChatSessionModal";
import { ChatPersonaSelector } from "./ChatPersonaSelector";
import { HEADER_PADDING } from "@/lib/constants";
import { FiSend, FiShare2, FiStopCircle } from "react-icons/fi";
import { ChatIntro } from "./ChatIntro";
import { AIMessage, HumanMessage } from "./message/Messages";
import { ThreeDots } from "react-loader-spinner";
import { StarterMessage } from "./StarterMessage";
import { SelectedDocuments } from "./modifiers/SelectedDocuments";
import { ChatFilters } from "./modifiers/ChatFilters";
import { AnswerPiecePacket, DanswerDocument } from "@/lib/search/interfaces";
import { buildFilters } from "@/lib/search/utils";
import { Tabs } from "./sessionSidebar/constants";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import Dropzone from "react-dropzone";
import { LLMProviderDescriptor } from "../admin/models/llm/interfaces";
import { checkLLMSupportsImageInput, getFinalLLM } from "@/lib/llm/utils";
import { InputBarPreviewImage } from "./images/InputBarPreviewImage";

const MAX_INPUT_HEIGHT = 200;

export function ChatPage({
  user,
  chatSessions,
  availableSources,
  availableDocumentSets,
  availablePersonas,
  availableTags,
  llmProviders,
  defaultSelectedPersonaId,
  documentSidebarInitialWidth,
  defaultSidebarTab,
  defaultModel,
  eea_config,
}: {
  user: User | null;
  chatSessions: ChatSession[];
  availableSources: ValidSources[];
  availableDocumentSets: DocumentSet[];
  availablePersonas: Persona[];
  availableTags: Tag[];
  llmProviders: LLMProviderDescriptor[];
  defaultSelectedPersonaId?: number; // what persona to default to
  documentSidebarInitialWidth?: number;
  defaultSidebarTab?: Tabs;
  defaultModel: string;
  eea_config: any;
}) {
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

    textareaRef.current?.focus();

    // only clear things if we're going from one chat session to another
    if (chatSessionId !== null && existingChatSessionId !== chatSessionId) {
      // de-select documents
      clearSelectedDocuments();
      // reset all filters
      filterManager.setSelectedDocumentSets([]);
      filterManager.setSelectedSources([]);
      filterManager.setSelectedTags([]);
      filterManager.setTimeRange(null);
      // remove uploaded files
      setCurrentMessageFileIds([]);

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
            availablePersonas.find(
              (persona) => persona.id === defaultSelectedPersonaId
            )
          );
        } else {
          setSelectedPersona(undefined);
        }
        setMessageHistory([]);
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
        availablePersonas.find(
          (persona) => persona.id === chatSession.persona_id
        )
      );

      const newMessageHistory = processRawChatHistory(chatSession.messages);
      // if the last message is an error, don't overwrite it
      if (messageHistory[messageHistory.length - 1]?.type !== "error") {
        setMessageHistory(newMessageHistory);

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
  const [messageHistory, setMessageHistory] = useState<Message[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);

  // uploaded files
  const [currentMessageFileIds, setCurrentMessageFileIds] = useState<string[]>(
    []
  );

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
      ? availablePersonas.find(
          (persona) => persona.id === existingChatSessionPersonaId
        )
      : defaultSelectedPersonaId !== undefined
        ? availablePersonas.find(
            (persona) => persona.id === defaultSelectedPersonaId
          )
        : undefined
  );
  const livePersona = selectedPersona || availablePersonas[0];

  const [chatSessionSharedStatus, setChatSessionSharedStatus] =
    useState<ChatSessionSharedStatus>(ChatSessionSharedStatus.Private);

  useEffect(() => {
    if (messageHistory.length === 0 && chatSessionId === null) {
      setSelectedPersona(
        availablePersonas.find(
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
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const textarea = textareaRef.current;
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
    const currFiles = currentMessageFileIds.map((id) => ({
      id,
      type: "image",
    })) as FileDescriptor[];
    setMessageHistory([
      ...currMessageHistory,
      {
        messageId: 0,
        message: currMessage,
        type: "user",
        files: currFiles,
      },
    ]);
    setMessage("");
    setCurrentMessageFileIds([]);

    setIsStreaming(true);
    let answer = "";
    let query: string | null = null;
    let retrievalType: RetrievalType =
      selectedDocuments.length > 0
        ? RetrievalType.SelectedDocs
        : RetrievalType.None;
    let documents: DanswerDocument[] = selectedDocuments;
    let error: string | null = null;
    let finalMessage: BackendMessage | null = null;
    try {
      const lastSuccessfulMessageId =
        getLastSuccessfulMessageId(currMessageHistory);
      for await (const packetBunch of sendMessage({
        message: currMessage,
        fileIds: currentMessageFileIds,
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
        modelVersion:
          searchParams.get(SEARCH_PARAM_NAMES.MODEL_VERSION) || undefined,
        temperature:
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
              setSelectedMessageForDocDisplay(-1);
            }
          } else if (Object.hasOwn(packet, "error")) {
            error = (packet as StreamingError).error;
          } else if (Object.hasOwn(packet, "message_id")) {
            finalMessage = packet as BackendMessage;
          }
        }
        setMessageHistory([
          ...currMessageHistory,
          {
            messageId: finalMessage?.parent_message || null,
            message: currMessage,
            type: "user",
            files: currFiles,
          },
          {
            messageId: finalMessage?.message_id || null,
            message: error || answer,
            type: error ? "error" : "assistant",
            retrievalType,
            query: finalMessage?.rephrased_query || query,
            documents: finalMessage?.context_docs?.top_documents || documents,
            citations: finalMessage?.citations || {},
            files: finalMessage?.files || [],
          },
        ]);
        if (isCancelledRef.current) {
          setIsCancelled(false);
          break;
        }
      }
    } catch (e: any) {
      const errorMsg = e.message;
      setMessageHistory([
        ...currMessageHistory,
        {
          messageId: null,
          message: currMessage,
          type: "user",
          files: currFiles,
        },
        {
          messageId: null,
          message: errorMsg,
          type: "error",
          files: [],
        },
      ]);
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
    feedbackDetails: string
  ) => {
    if (chatSessionId === null) {
      return;
    }

    const response = await handleChatFeedback(
      messageId,
      feedbackType,
      feedbackDetails
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
      setCurrentMessageFileIds([]);

      setSelectedPersona(persona);
      textareaRef.current?.focus();
      router.push(buildChatUrl(searchParams, null, persona.id));
    }
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
      <div className="absolute top-0 z-40 w-full">
        <Header user={user} />
      </div>
      <HealthCheckBanner />
      <InstantSSRAutoRefresh />

      <div className="flex relative bg-background text-default overflow-x-hidden">
        <ChatSidebar
          existingChats={chatSessions}
          currentChatSession={selectedChatSession}
          personas={availablePersonas}
          onPersonaChange={onPersonaChange}
          user={user}
          defaultTab={defaultSidebarTab}
        />
        <div className="flex w-full overflow-x-hidden" ref={masterFlexboxRef}>
          {popup}
          {currentFeedback && (
            <FeedbackModal
              feedbackType={currentFeedback[0]}
              onClose={() => setCurrentFeedback(null)}
              onSubmit={(feedbackDetails) => {
                onFeedback(
                  currentFeedback[1],
                  currentFeedback[0],
                  feedbackDetails
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

          {documentSidebarInitialWidth !== undefined ? (
            <Dropzone
              onDrop={(acceptedFiles) => {
                const llmAcceptsImages = checkLLMSupportsImageInput(
                  ...getFinalLLM(llmProviders, livePersona)
                );
                if (!llmAcceptsImages) {
                  setPopup({
                    type: "error",
                    message:
                      "The current Assistant does not support image input. Please select an assistant with Vision support.",
                  });
                  return;
                }

                uploadFilesForChat(acceptedFiles).then(([fileIds, error]) => {
                  if (error) {
                    setPopup({
                      type: "error",
                      message: error,
                    });
                  } else {
                    const newFileIds = [...currentMessageFileIds, ...fileIds];
                    setCurrentMessageFileIds(newFileIds);
                  }
                });
              }}
              noClick
              onDragLeave={() => console.log("buh")}
              onDragEnter={() => console.log("floppa")}
            >
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
                      className={`w-full h-full ${HEADER_PADDING} flex flex-col overflow-y-auto overflow-x-hidden relative`}
                      ref={scrollableDivRef}
                    >
                      {livePersona && (
                        <div className="sticky top-0 left-80 z-10 w-full bg-background/90 flex">
                          <div className="ml-2 p-1 rounded mt-2 w-fit">
                            <ChatPersonaSelector
                              personas={availablePersonas}
                              selectedPersonaId={livePersona.id}
                              defaultModel={defaultModel}
                              onPersonaChange={onPersonaChange}
                            />
                          </div>

                          {chatSessionId !== null && (
                            <div
                              onClick={() => setSharingModalVisible(true)}
                              className="ml-auto mr-6 my-auto border-border border p-2 rounded cursor-pointer hover:bg-hover-light"
                            >
                              <FiShare2 />
                            </div>
                          )}
                        </div>
                      )}

                      {messageHistory.length === 0 &&
                        !isFetchingChatMessages &&
                        !isStreaming && (
                          <ChatIntro
                            availableSources={finalAvailableSources}
                            availablePersonas={availablePersonas}
                            selectedPersona={selectedPersona}
                            defaultModel={defaultModel}
                            handlePersonaSelect={(persona) => {
                              setSelectedPersona(persona);
                              textareaRef.current?.focus();
                              router.push(
                                buildChatUrl(searchParams, null, persona.id)
                              );
                            }}
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
                            return (
                              <div key={i}>
                                <HumanMessage
                                  content={message.message}
                                  files={message.files}
                                />
                              </div>
                            );
                          } else if (message.type === "assistant") {
                            const isShowingRetrieved =
                              (selectedMessageForDocDisplay !== null &&
                                selectedMessageForDocDisplay ===
                                  message.messageId) ||
                              (selectedMessageForDocDisplay === -1 &&
                                i === messageHistory.length - 1);
                            const previousMessage =
                              i !== 0 ? messageHistory[i - 1] : null;
                            return (
                              <div key={i}>
                                <AIMessage
                                  messageId={message.messageId}
                                  content={message.message}
                                  query={messageHistory[i]?.query || undefined}
                                  personaName={livePersona.name}
                                  citedDocuments={getCitedDocumentsFromMessage(
                                    message
                                  )}
                                  isComplete={
                                    i !== messageHistory.length - 1 ||
                                    !isStreaming
                                  }
                                  hasDocs={
                                    (message.documents &&
                                      message.documents.length > 0) === true
                                  }
                                  handleFeedback={
                                    i === messageHistory.length - 1 &&
                                    isStreaming
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
                                  isCurrentlyShowingRetrieved={
                                    isShowingRetrieved
                                  }
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
                              </div>
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
                          messageHistory.length &&
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
                        <div className={`min-h-[30px] w-full`}></div>

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

                    <div className="absolute bottom-0 z-10 w-full bg-background border-t border-border">
                      <div className="w-full pb-4 pt-2">
                        {!retrievalDisabled && (
                          <div className="flex">
                            <div className="w-searchbar-xs 2xl:w-searchbar-sm 3xl:w-searchbar mx-auto px-4 pt-1 flex">
                              {selectedDocuments.length > 0 ? (
                                <SelectedDocuments
                                  selectedDocuments={selectedDocuments}
                                />
                              ) : (
                                <ChatFilters
                                  {...filterManager}
                                  existingSources={finalAvailableSources}
                                  availableDocumentSets={
                                    finalAvailableDocumentSets
                                  }
                                  availableTags={availableTags}
                                />
                              )}
                            </div>
                          </div>
                        )}

                        <div className="flex justify-center py-2 max-w-screen-lg mx-auto mb-2">
                          <div className="w-full shrink relative px-4 w-searchbar-xs 2xl:w-searchbar-sm 3xl:w-searchbar mx-auto">
                            <div
                              className={`
                              opacity-100
                              w-full
                              h-fit
                              flex
                              flex-col
                              border 
                              border-border 
                              rounded-lg 
                              [&:has(textarea:focus)]::ring-1
                              [&:has(textarea:focus)]::ring-black
                            `}
                            >
                              {currentMessageFileIds.length > 0 && (
                                <div className="flex flex-wrap gap-y-2 px-1">
                                  {currentMessageFileIds.map((fileId) => (
                                    <div key={fileId} className="py-1">
                                      <InputBarPreviewImage
                                        fileId={fileId}
                                        onDelete={() => {
                                          setCurrentMessageFileIds(
                                            currentMessageFileIds.filter(
                                              (id) => id !== fileId
                                            )
                                          );
                                        }}
                                      />
                                    </div>
                                  ))}
                                </div>
                              )}
                              <textarea
                                ref={textareaRef}
                                className={`
                                  m-0 
                                  w-full 
                                  shrink
                                  resize-none 
                                  border-0 
                                  bg-transparent 
                                  ${
                                    (textareaRef?.current?.scrollHeight || 0) >
                                    MAX_INPUT_HEIGHT
                                      ? "overflow-y-auto"
                                      : ""
                                  } 
                                  whitespace-normal 
                                  break-word
                                  overscroll-contain
                                  outline-none 
                                  placeholder-gray-400 
                                  overflow-hidden
                                  resize-none
                                  pl-4
                                  pr-12 
                                  py-4 
                                  h-14`}
                                autoFocus
                                style={{ scrollbarWidth: "thin" }}
                                role="textarea"
                                aria-multiline
                                placeholder="Ask me anything..."
                                value={message}
                                onChange={(e) => setMessage(e.target.value)}
                                onKeyDown={(event) => {
                                  if (
                                    event.key === "Enter" &&
                                    !event.shiftKey &&
                                    message &&
                                    !isStreaming
                                  ) {
                                    onSubmit();
                                    event.preventDefault();
                                  }
                                }}
                                suppressContentEditableWarning={true}
                              />
                            </div>
                            <div className="absolute bottom-2.5 right-10">
                              <div
                                className={"cursor-pointer"}
                                onClick={() => {
                                  if (!isStreaming) {
                                    if (message) {
                                      onSubmit();
                                    }
                                  } else {
                                    setIsCancelled(true);
                                  }
                                }}
                              >
                                {isStreaming ? (
                                  <FiStopCircle
                                    size={18}
                                    className={
                                      "text-emphasis w-9 h-9 p-2 rounded-lg hover:bg-hover"
                                    }
                                  />
                                ) : (
                                  <FiSend
                                    size={18}
                                    className={
                                      "text-emphasis w-9 h-9 p-2 rounded-lg " +
                                      (message ? "bg-blue-200" : "")
                                    }
                                  />
                                )}
                              </div>
                            </div>
                          </div>
                        </div>
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
      <Footer eea_config={eea_config}/>
    </>
  );
}
