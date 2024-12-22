"use client";

import { useRouter, useSearchParams } from "next/navigation";
import {
  BackendChatSession,
  BackendMessage,
  BUFFER_COUNT,
  ChatFileType,
  ChatSession,
  ChatSessionSharedStatus,
  FileDescriptor,
  FileChatDisplay,
  Message,
} from "../chat/interfaces";

import Prism from "prismjs";
import Cookies from "js-cookie";
import { Persona } from "../admin/assistants/interfaces";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import {
  buildChatUrl,
  buildLatestMessageChain,
  checkAnyAssistantHasSearch,
  createChatSession,
  deleteAllChatSessions,
  deleteChatSession,
  getCitedDocumentsFromMessage,
  getHumanAndAIMessageFromMessageNumber,
  getLastSuccessfulMessageId,
  handleChatFeedback,
  nameChatSession,
  PacketType,
  personaIncludesRetrieval,
  processRawChatHistory,
  removeMessage,
  sendMessage,
  setMessageAsLatest,
  updateParentChildren,
  uploadFilesForChat,
  useScrollonStream,
} from "../chat/lib";
import {
  Dispatch,
  SetStateAction,
  useContext,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  useMemo,
} from "react";
import { usePopup } from "@/components/admin/connectors/Popup";
import { OnyxInitializingLoader } from "@/components/OnyxInitializingLoader";
import { FiArrowDown } from "react-icons/fi";
import { StarterMessages } from "../../components/assistants/StarterMessage";

import {
  AnswerPiecePacket,
  OnyxDocument,
  DocumentInfoPacket,
  StreamStopInfo,
  StreamStopReason,
} from "@/lib/search/interfaces";
import { buildFilters } from "@/lib/search/utils";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import Dropzone from "react-dropzone";
import {
  checkLLMSupportsImageInput,
  getFinalLLM,
  destructureValue,
  getLLMProviderOverrideForPersona,
} from "@/lib/llm/utils";

import { useChatContext } from "@/components/context/ChatContext";
import { v4 as uuidv4 } from "uuid";

import FunctionalHeader from "@/components/chat_search/Header";
import { useSidebarVisibility } from "@/components/chat_search/hooks";
import { SIDEBAR_TOGGLED_COOKIE_NAME } from "@/components/resizable/constants";
import { DeleteEntityModal } from "../../components/modals/DeleteEntityModal";
import { MinimalMarkdown } from "@/components/chat_search/MinimalMarkdown";
import { useUser } from "@/components/user/UserProvider";
import { ApiKeyModal } from "@/components/llm/ApiKeyModal";
import { NoAssistantModal } from "@/components/modals/NoAssistantModal";
import { useAssistants } from "@/components/context/AssistantsContext";
import { Separator } from "@/components/ui/separator";
import AssistantBanner from "../../components/assistants/AssistantBanner";
import AssistantSelector from "@/components/chat_search/AssistantSelector";
import { ChatPopup } from "../chat/ChatPopup";
import FixedLogo from "../chat/shared_chat_search/FixedLogo";
import { ChatInputBar } from "../chat/input/ChatInputBar";
import { LlmOverride, useLlmOverride } from "@/lib/hooks";
import { HistorySidebar } from "../chat/sessionSidebar/HistorySidebar";
import BlurBackground from "../chat/shared_chat_search/BlurBackground";
import { ChatIntro } from "../chat/ChatIntro";
import { SEARCH_PARAM_NAMES, shouldSubmitOnLoad } from "../chat/searchParams";
import { Switch } from "@/components/ui/switch";

const TEMP_USER_MESSAGE_ID = -1;
const TEMP_ASSISTANT_MESSAGE_ID = -2;
const SYSTEM_MESSAGE_ID = -3;

export default function NRFPage({
  toggle,
  documentSidebarInitialWidth,
  toggledSidebar,
}: {
  toggle: (toggled?: boolean) => void;
  documentSidebarInitialWidth?: number;
  toggledSidebar: boolean;
}) {
  const router = useRouter();
  const searchParams = useSearchParams();

  const {
    chatSessions,
    ccPairs,
    tags,
    documentSets,
    llmProviders,
    folders,
    openedFolders,
    defaultAssistantId,
    shouldShowWelcomeModal,
    refreshChatSessions,
  } = useChatContext();
  function useScreenSize() {
    const [screenSize, setScreenSize] = useState({
      width: typeof window !== "undefined" ? window.innerWidth : 0,
      height: typeof window !== "undefined" ? window.innerHeight : 0,
    });

    useEffect(() => {
      const handleResize = () => {
        setScreenSize({
          width: window.innerWidth,
          height: window.innerHeight,
        });
      };

      window.addEventListener("resize", handleResize);
      return () => window.removeEventListener("resize", handleResize);
    }, []);

    return screenSize;
  }

  const { height: screenHeight } = useScreenSize();

  const getContainerHeight = () => {
    if (autoScrollEnabled) return undefined;

    if (screenHeight < 600) return "20vh";
    if (screenHeight < 1200) return "30vh";
    return "40vh";
  };

  // handle redirect if chat page is disabled
  // NOTE: this must be done here, in a client component since
  // settings are passed in via Context and therefore aren't
  // available in server-side components
  const settings = useContext(SettingsContext);
  const enterpriseSettings = settings?.enterpriseSettings;

  const [documentSidebarToggled, setDocumentSidebarToggled] = useState(false);
  const [filtersToggled, setFiltersToggled] = useState(false);

  const [userSettingsToggled, setUserSettingsToggled] = useState(false);

  const { assistants: availableAssistants, finalAssistants } = useAssistants();

  const [showApiKeyModal, setShowApiKeyModal] = useState(
    !shouldShowWelcomeModal
  );

  const { user, isAdmin } = useUser();
  const slackChatId = searchParams.get("slackChatId");
  const existingChatIdRaw = searchParams.get("chatId");
  const [sendOnLoad, setSendOnLoad] = useState<string | null>(
    searchParams.get(SEARCH_PARAM_NAMES.SEND_ON_LOAD)
  );

  const modelVersionFromSearchParams = searchParams.get(
    SEARCH_PARAM_NAMES.STRUCTURED_MODEL
  );

  // Effect to handle sendOnLoad
  useEffect(() => {
    if (sendOnLoad) {
      const newSearchParams = new URLSearchParams(searchParams.toString());
      newSearchParams.delete(SEARCH_PARAM_NAMES.SEND_ON_LOAD);

      // Update the URL without the send-on-load parameter
      router.replace(`?${newSearchParams.toString()}`, { scroll: false });

      // Update our local state to reflect the change
      setSendOnLoad(null);

      // If there's a message, submit it
      if (message) {
        onSubmit({ messageOverride: message });
      }
    }
  }, [sendOnLoad, searchParams, router]);

  const existingChatSessionId = existingChatIdRaw ? existingChatIdRaw : null;

  const selectedChatSession = chatSessions.find(
    (chatSession) => chatSession.id === existingChatSessionId
  );

  const chatSessionIdRef = useRef<string | null>(existingChatSessionId);

  // Only updates on session load (ie. rename / switching chat session)
  // Useful for determining which session has been loaded (i.e. still on `new, empty session` or `previous session`)
  const loadedIdSessionRef = useRef<string | null>(existingChatSessionId);

  const existingChatSessionAssistantId = selectedChatSession?.persona_id;
  const [selectedAssistant, setSelectedAssistant] = useState<
    Persona | undefined
  >(
    // NOTE: look through available assistants here, so that even if the user
    // has hidden this assistant it still shows the correct assistant when
    // going back to an old chat session
    existingChatSessionAssistantId !== undefined
      ? availableAssistants.find(
          (assistant) => assistant.id === existingChatSessionAssistantId
        )
      : defaultAssistantId !== undefined
        ? availableAssistants.find(
            (assistant) => assistant.id === defaultAssistantId
          )
        : undefined
  );
  // Gather default temperature settings
  const search_param_temperature = searchParams.get(
    SEARCH_PARAM_NAMES.TEMPERATURE
  );

  const defaultTemperature = search_param_temperature
    ? parseFloat(search_param_temperature)
    : selectedAssistant?.tools.some(
          (tool) =>
            tool.in_code_tool_id === "SearchTool" ||
            tool.in_code_tool_id === "InternetSearchTool"
        )
      ? 0
      : 0.7;

  const setSelectedAssistantFromId = (assistantId: number) => {
    // NOTE: also intentionally look through available assistants here, so that
    // even if the user has hidden an assistant they can still go back to it
    // for old chats
    setSelectedAssistant(
      availableAssistants.find((assistant) => assistant.id === assistantId)
    );
  };

  const llmOverrideManager = useLlmOverride(
    llmProviders,
    modelVersionFromSearchParams || (user?.preferences.default_model ?? null),
    selectedChatSession,
    defaultTemperature
  );

  const [alternativeAssistant, setAlternativeAssistant] =
    useState<Persona | null>(null);

  const [presentingDocument, setPresentingDocument] =
    useState<OnyxDocument | null>(null);

  const {
    visibleAssistants: assistants,
    recentAssistants,
    assistants: allAssistants,
    refreshRecentAssistants,
  } = useAssistants();

  const liveAssistant: Persona | undefined =
    alternativeAssistant ||
    selectedAssistant ||
    recentAssistants[0] ||
    finalAssistants[0] ||
    availableAssistants[0];

  const noAssistants = liveAssistant == null || liveAssistant == undefined;

  const availableSources = ccPairs.map((ccPair) => ccPair.source);

  // always set the model override for the chat session, when an assistant, llm provider, or user preference exists
  useEffect(() => {
    if (noAssistants) return;
    const personaDefault = getLLMProviderOverrideForPersona(
      liveAssistant,
      llmProviders
    );

    if (personaDefault) {
      llmOverrideManager.updateLLMOverride(personaDefault);
    } else if (user?.preferences.default_model) {
      llmOverrideManager.updateLLMOverride(
        destructureValue(user?.preferences.default_model)
      );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveAssistant, user?.preferences.default_model]);

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
  };

  // this is for "@"ing assistants

  // this is used to track which assistant is being used to generate the current message
  // for example, this would come into play when:
  // 1. default assistant is `Onyx`
  // 2. we "@"ed the `GPT` assistant and sent a message
  // 3. while the `GPT` assistant message is generating, we "@" the `Paraphrase` assistant
  const [alternativeGeneratingAssistant, setAlternativeGeneratingAssistant] =
    useState<Persona | null>(null);

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

  const [isReady, setIsReady] = useState(false);

  useEffect(() => {
    Prism.highlightAll();
    setIsReady(true);
  }, []);

  // this is triggered every time the user switches which chat
  // session they are using
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

      // reset LLM overrides (based on chat session!)
      llmOverrideManager.updateModelOverrideForChatSession(selectedChatSession);
      llmOverrideManager.updateTemperature(null);

      // remove uploaded files
      setCurrentMessageFiles([]);

      // if switching from one chat to another, then need to scroll again
      // if we're creating a brand new chat, then don't need to scroll
      if (chatSessionIdRef.current !== null) {
        setHasPerformedInitialScroll(false);
      }
    }

    async function initialSessionFetch() {
      if (existingChatSessionId === null) {
        setIsFetchingChatMessages(false);
        if (defaultAssistantId !== undefined) {
          setSelectedAssistantFromId(defaultAssistantId);
        } else {
          setSelectedAssistant(undefined);
        }
        updateCompleteMessageDetail(null, new Map());
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
      setIsReady(true);
      const shouldScrollToBottom =
        visibleRange.get(existingChatSessionId) === undefined ||
        visibleRange.get(existingChatSessionId)?.end == 0;

      setIsFetchingChatMessages(true);
      const response = await fetch(
        `/api/chat/get-chat-session/${existingChatSessionId}`
      );

      const chatSession = (await response.json()) as BackendChatSession;
      setSelectedAssistantFromId(chatSession.persona_id);

      const newMessageMap = processRawChatHistory(chatSession.messages);
      const newMessageHistory = buildLatestMessageChain(newMessageMap);

      // Update message history except for edge where where
      // last message is an error and we're on a new chat.
      // This corresponds to a "renaming" of chat, which occurs after first message
      // stream
      if (
        messageHistory[messageHistory.length - 1]?.type !== "error" ||
        loadedSessionId != null
      ) {
        const latestMessageId =
          newMessageHistory[newMessageHistory.length - 1]?.messageId;

        setSelectedMessageForDocDisplay(
          latestMessageId !== undefined ? latestMessageId : null
        );

        updateCompleteMessageDetail(chatSession.chat_session_id, newMessageMap);
      }

      setChatSessionSharedStatus(chatSession.shared_status);

      // go to bottom. If initial load, then do a scroll,
      // otherwise just appear at the bottom
      if (shouldScrollToBottom) {
        scrollInitialized.current = false;
      }

      if (shouldScrollToBottom) {
        if (!hasPerformedInitialScroll && autoScrollEnabled) {
          clientScrollToBottom();
        } else if (isChatSessionSwitch && autoScrollEnabled) {
          clientScrollToBottom(true);
        }
      }

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
  }, [existingChatSessionId]);

  const [message, setMessage] = useState(
    searchParams.get(SEARCH_PARAM_NAMES.USER_PROMPT) || ""
  );

  const [completeMessageDetail, setCompleteMessageDetail] = useState<
    Map<string | null, Map<number, Message>>
  >(new Map());

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
    replacementsMap = null,
    makeLatestChildMessage = false,
  }: {
    messages: Message[];
    // if calling this function repeatedly with short delay, stay may not update in time
    // and result in weird behavipr
    completeMessageMapOverride?: Map<number, Message> | null;
    chatSessionId?: string;
    replacementsMap?: Map<number, number> | null;
    makeLatestChildMessage?: boolean;
  }) => {
    // deep copy
    const frozenCompleteMessageMap =
      completeMessageMapOverride || currentMessageMap(completeMessageDetail);
    const newCompleteMessageMap = structuredClone(frozenCompleteMessageMap);

    if (newCompleteMessageMap.size === 0) {
      const systemMessageId = messages[0].parentMessageId || SYSTEM_MESSAGE_ID;
      const firstMessageId = messages[0].messageId;
      const dummySystemMessage: Message = {
        messageId: systemMessageId,
        message: "",
        type: "system",
        files: [],
        toolCall: null,
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

    const newCompleteMessageDetail = {
      sessionId: chatSessionId || currentSessionId(),
      messageMap: newCompleteMessageMap,
    };

    updateCompleteMessageDetail(
      chatSessionId || currentSessionId(),
      newCompleteMessageMap
    );
    return newCompleteMessageDetail;
  };

  const messageHistory = buildLatestMessageChain(
    currentMessageMap(completeMessageDetail)
  );

  const [abortControllers, setAbortControllers] = useState<
    Map<string | null, AbortController>
  >(new Map());

  // Updates "null" session values to new session id for
  // regeneration, chat, and abort controller state, messagehistory
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

  const [chatSessionSharedStatus, setChatSessionSharedStatus] =
    useState<ChatSessionSharedStatus>(ChatSessionSharedStatus.Private);

  useEffect(() => {
    if (messageHistory.length === 0 && chatSessionIdRef.current === null) {
      // Select from available assistants so shared assistants appear.
      setSelectedAssistant(
        availableAssistants.find((persona) => persona.id === defaultAssistantId)
      );
    }
  }, [defaultAssistantId, availableAssistants, messageHistory.length]);

  // just choose a conservative default, this will be updated in the
  // background on initial load / on persona change
  const [maxTokens, setMaxTokens] = useState<number>(4096);

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
    refreshRecentAssistants(liveAssistant?.id);
    fetchMaxTokens();
  }, [liveAssistant]);

  const [sharingModalVisible, setSharingModalVisible] =
    useState<boolean>(false);

  const [aboveHorizon, setAboveHorizon] = useState(false);

  const scrollableDivRef = useRef<HTMLDivElement>(null);
  const lastMessageRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLDivElement>(null);
  const endDivRef = useRef<HTMLDivElement>(null);
  const endPaddingRef = useRef<HTMLDivElement>(null);

  const previousHeight = useRef<number>(
    inputRef.current?.getBoundingClientRect().height!
  );
  const scrollDist = useRef<number>(0);

  const updateScrollTracking = () => {
    const scrollDistance =
      endDivRef?.current?.getBoundingClientRect()?.top! -
      inputRef?.current?.getBoundingClientRect()?.top!;
    scrollDist.current = scrollDistance;
    setAboveHorizon(scrollDist.current > 500);
  };

  useEffect(() => {
    const scrollableDiv = scrollableDivRef.current;
    if (scrollableDiv) {
      scrollableDiv.addEventListener("scroll", updateScrollTracking);
      return () => {
        scrollableDiv.removeEventListener("scroll", updateScrollTracking);
      };
    }
  }, []);

  const handleInputResize = () => {
    setTimeout(() => {
      if (
        inputRef.current &&
        lastMessageRef.current &&
        !waitForScrollRef.current
      ) {
        const newHeight: number =
          inputRef.current?.getBoundingClientRect().height!;
        const heightDifference = newHeight - previousHeight.current;
        if (
          previousHeight.current &&
          heightDifference != 0 &&
          endPaddingRef.current &&
          scrollableDivRef &&
          scrollableDivRef.current
        ) {
          endPaddingRef.current.style.transition = "height 0.3s ease-out";
          endPaddingRef.current.style.height = `${Math.max(
            newHeight - 50,
            0
          )}px`;

          if (autoScrollEnabled) {
            scrollableDivRef?.current.scrollBy({
              left: 0,
              top: Math.max(heightDifference, 0),
              behavior: "smooth",
            });
          }
        }
        previousHeight.current = newHeight;
      }
    }, 100);
  };

  const clientScrollToBottom = (fast?: boolean) => {
    waitForScrollRef.current = true;

    setTimeout(() => {
      if (!endDivRef.current || !scrollableDivRef.current) {
        console.error("endDivRef or scrollableDivRef not found");
        return;
      }

      const rect = endDivRef.current.getBoundingClientRect();
      const isVisible = rect.top >= 0 && rect.bottom <= window.innerHeight;

      if (isVisible) return;

      // Check if all messages are currently rendered
      if (currentVisibleRange.end < messageHistory.length) {
        // Update visible range to include the last messages
        updateCurrentVisibleRange({
          start: Math.max(
            0,
            messageHistory.length -
              (currentVisibleRange.end - currentVisibleRange.start)
          ),
          end: messageHistory.length,
          mostVisibleMessageId: currentVisibleRange.mostVisibleMessageId,
        });

        // Wait for the state update and re-render before scrolling
        setTimeout(() => {
          endDivRef.current?.scrollIntoView({
            behavior: fast ? "auto" : "smooth",
          });
          setHasPerformedInitialScroll(true);
        }, 100);
      } else {
        // If all messages are already rendered, scroll immediately
        endDivRef.current.scrollIntoView({
          behavior: fast ? "auto" : "smooth",
        });

        setHasPerformedInitialScroll(true);
      }
    }, 50);

    // Reset waitForScrollRef after 1.5 seconds
    setTimeout(() => {
      waitForScrollRef.current = false;
    }, 1500);
  };

  const debounceNumber = 100; // time for debouncing

  const [hasPerformedInitialScroll, setHasPerformedInitialScroll] = useState(
    existingChatSessionId === null
  );

  // handle re-sizing of the text area
  const textAreaRef = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    handleInputResize();
  }, [message]);

  // tracks scrolling
  useEffect(() => {
    updateScrollTracking();
  }, [messageHistory]);

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

  async function updateCurrentMessageFIFO(
    stack: CurrentMessageFIFO,
    params: any
  ) {
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

  const resetInputBar = () => {
    setMessage("");
    setCurrentMessageFiles([]);
    if (endPaddingRef.current) {
      endPaddingRef.current.style.height = `95px`;
    }
  };

  const continueGenerating = () => {
    onSubmit({
      messageOverride:
        "Continue Generating (pick up exactly where you left off)",
    });
  };

  const onSubmit = async ({
    messageIdToResend,
    messageOverride,
    queryOverride,
    forceSearch,
    isSeededChat,
    alternativeAssistantOverride = null,
    modelOverRide,
    regenerationRequest,
  }: {
    messageIdToResend?: number;
    messageOverride?: string;
    queryOverride?: string;
    forceSearch?: boolean;
    isSeededChat?: boolean;
    alternativeAssistantOverride?: Persona | null;
    modelOverRide?: LlmOverride;
    regenerationRequest?: RegenerationRequest | null;
  } = {}) => {
    if (window?.top?.location) {
      window.top.location.href = buildChatUrl(
        searchParams,
        null,
        liveAssistant.id
      );
    }
  };

  const onAssistantChange = (assistant: Persona | null) => {
    if (assistant && assistant.id !== liveAssistant.id) {
      // Abort the ongoing stream if it exists
      textAreaRef.current?.focus();
      router.push(buildChatUrl(searchParams, null, assistant.id));
    }
  };

  const handleImageUpload = async (acceptedFiles: File[]) => {
    const [_, llmModel] = getFinalLLM(
      llmProviders,
      liveAssistant,
      llmOverrideManager.llmOverride
    );
    const llmAcceptsImages = checkLLMSupportsImageInput(llmModel);

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

    await uploadFilesForChat(acceptedFiles).then(([files, error]) => {
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

  const [showHistorySidebar, setShowHistorySidebar] = useState(false); // State to track if sidebar is open

  // Used to maintain a "time out" for history sidebar so our existing refs can have time to process change
  const [untoggled, setUntoggled] = useState(false);
  const [loadingError, setLoadingError] = useState<string | null>(null);

  const explicitlyUntoggle = () => {
    setShowHistorySidebar(false);

    setUntoggled(true);
    setTimeout(() => {
      setUntoggled(false);
    }, 200);
  };

  const toggleSidebar = () => {
    Cookies.set(
      SIDEBAR_TOGGLED_COOKIE_NAME,
      String(!toggledSidebar).toLocaleLowerCase()
    ),
      {
        path: "/",
      };

    toggle();
  };
  const removeToggle = () => {
    setShowHistorySidebar(false);
    toggle(false);
  };

  const waitForScrollRef = useRef(false);
  const sidebarElementRef = useRef<HTMLDivElement>(null);

  useSidebarVisibility({
    toggledSidebar,
    sidebarElementRef,
    showDocSidebar: showHistorySidebar,
    setShowDocSidebar: setShowHistorySidebar,
    setToggled: removeToggle,
    mobile: settings?.isMobile,
  });

  const autoScrollEnabled =
    user?.preferences?.auto_scroll == null
      ? settings?.enterpriseSettings?.auto_scroll || false
      : user?.preferences?.auto_scroll!;

  // Virtualization + Scrolling related effects and functions
  const scrollInitialized = useRef(false);
  interface VisibleRange {
    start: number;
    end: number;
    mostVisibleMessageId: number | null;
  }

  const [visibleRange, setVisibleRange] = useState<
    Map<string | null, VisibleRange>
  >(() => {
    const initialRange: VisibleRange = {
      start: 0,
      end: BUFFER_COUNT,
      mostVisibleMessageId: null,
    };
    return new Map([[chatSessionIdRef.current, initialRange]]);
  });

  // Function used to update current visible range. Only method for updating `visibleRange` state.
  const updateCurrentVisibleRange = (
    newRange: VisibleRange,
    forceUpdate?: boolean
  ) => {
    if (
      scrollInitialized.current &&
      visibleRange.get(loadedIdSessionRef.current) == undefined &&
      !forceUpdate
    ) {
      return;
    }

    setVisibleRange((prevState) => {
      const newState = new Map(prevState);
      newState.set(loadedIdSessionRef.current, newRange);
      return newState;
    });
  };

  //  Set first value for visibleRange state on page load / refresh.
  const initializeVisibleRange = () => {
    const upToDatemessageHistory = buildLatestMessageChain(
      currentMessageMap(completeMessageDetail)
    );

    if (!scrollInitialized.current && upToDatemessageHistory.length > 0) {
      const newEnd = Math.max(upToDatemessageHistory.length, BUFFER_COUNT);
      const newStart = Math.max(0, newEnd - BUFFER_COUNT);
      const newMostVisibleMessageId =
        upToDatemessageHistory[newEnd - 1]?.messageId;

      updateCurrentVisibleRange(
        {
          start: newStart,
          end: newEnd,
          mostVisibleMessageId: newMostVisibleMessageId,
        },
        true
      );
      scrollInitialized.current = true;
    }
  };

  useEffect(() => {
    initializeVisibleRange();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router, messageHistory]);

  const currentVisibleRange = visibleRange.get(currentSessionId()) || {
    start: 0,
    end: 0,
    mostVisibleMessageId: null,
  };

  useEffect(() => {
    if (noAssistants) {
      return;
    }
    const includes = checkAnyAssistantHasSearch(
      messageHistory,
      availableAssistants,
      liveAssistant
    );
    setRetrievalEnabled(includes);
  }, [messageHistory, availableAssistants, liveAssistant]);

  const [retrievalEnabled, setRetrievalEnabled] = useState(() => {
    if (noAssistants) {
      return false;
    }
    return checkAnyAssistantHasSearch(
      messageHistory,
      availableAssistants,
      liveAssistant
    );
  });

  useEffect(() => {
    if (!retrievalEnabled) {
      setDocumentSidebarToggled(false);
    }
  }, [retrievalEnabled]);

  const [stackTraceModalContent, setStackTraceModalContent] = useState<
    string | null
  >(null);

  const innerSidebarElementRef = useRef<HTMLDivElement>(null);
  const [settingsToggled, setSettingsToggled] = useState(false);
  const [showDeleteAllModal, setShowDeleteAllModal] = useState(false);

  const currentPersona = alternativeAssistant || liveAssistant;
  useEffect(() => {
    const handleSlackChatRedirect = async () => {
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
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey) {
        switch (event.key.toLowerCase()) {
          case "e":
            event.preventDefault();
            toggleSidebar();
            break;
        }
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router]);
  const [sharedChatSession, setSharedChatSession] =
    useState<ChatSession | null>();
  const [deletingChatSession, setDeletingChatSession] =
    useState<ChatSession | null>();

  const showDeleteModal = (chatSession: ChatSession) => {
    setDeletingChatSession(chatSession);
  };
  const showShareModal = (chatSession: ChatSession) => {
    setSharedChatSession(chatSession);
  };

  const toggleDocumentSidebar = () => {
    if (!documentSidebarToggled) {
      setFiltersToggled(false);
      setDocumentSidebarToggled(true);
    } else if (!filtersToggled) {
      setDocumentSidebarToggled(false);
    } else {
      setFiltersToggled(false);
    }
  };
  const toggleFilters = () => {
    if (!documentSidebarToggled) {
      setFiltersToggled(true);
      setDocumentSidebarToggled(true);
    } else if (filtersToggled) {
      setDocumentSidebarToggled(false);
    } else {
      setFiltersToggled(true);
    }
  };

  interface RegenerationRequest {
    messageId: number;
    parentMessage: Message;
    forceSearch?: boolean;
  }

  function createRegenerator(regenerationRequest: RegenerationRequest) {
    // Returns new function that only needs `modelOverRide` to be specified when called
    return async function (modelOverRide: LlmOverride) {
      return await onSubmit({
        modelOverRide,
        messageIdToResend: regenerationRequest.parentMessage.messageId,
        regenerationRequest,
        forceSearch: regenerationRequest.forceSearch,
      });
    };
  }
  if (noAssistants)
    return (
      <>
        <HealthCheckBanner />
        <NoAssistantModal isAdmin={isAdmin} />
      </>
    );

  return (
    <>
      <HealthCheckBanner />

      {showApiKeyModal && !shouldShowWelcomeModal && (
        <ApiKeyModal
          hide={() => setShowApiKeyModal(false)}
          setPopup={setPopup}
        />
      )}

      {/* ChatPopup is a custom popup that displays a admin-specified message on initial user visit. 
      Only used in the EE version of the app. */}
      {popup}

      <ChatPopup />

      {deletingChatSession && (
        <DeleteEntityModal
          entityType="chat"
          entityName={deletingChatSession.name.slice(0, 30)}
          onClose={() => setDeletingChatSession(null)}
          onSubmit={async () => {
            const response = await deleteChatSession(deletingChatSession.id);
            if (response.ok) {
              setDeletingChatSession(null);
              // go back to the main page
              if (deletingChatSession.id === chatSessionIdRef.current) {
                router.push("/chat");
              }
            } else {
              const responseJson = await response.json();
              setPopup({ message: responseJson.detail, type: "error" });
            }
            refreshChatSessions();
          }}
        />
      )}

      <div className="fixed  inset-0 flex flex-col text-default">
        <div className="h-[100dvh] overflow-y-hidden">
          <div className="w-full">
            <div
              ref={sidebarElementRef}
              className={`
                flex-none
                fixed
                left-0
                z-40
                bg-background-100
                h-screen
                transition-all
                bg-opacity-80
                duration-300
                ease-in-out
                ${
                  !untoggled && (showHistorySidebar || toggledSidebar)
                    ? "opacity-100 w-[250px] translate-x-0"
                    : "opacity-0 w-[200px] pointer-events-none -translate-x-10"
                }`}
            >
              <div className="w-full relative">
                <HistorySidebar
                  explicitlyUntoggle={explicitlyUntoggle}
                  stopGenerating={stopGenerating}
                  reset={() => setMessage("")}
                  page="chat"
                  ref={innerSidebarElementRef}
                  toggleSidebar={toggleSidebar}
                  toggled={toggledSidebar}
                  backgroundToggled={toggledSidebar || showHistorySidebar}
                  existingChats={chatSessions}
                  currentChatSession={selectedChatSession}
                  folders={folders}
                  openedFolders={openedFolders}
                  removeToggle={removeToggle}
                  showShareModal={showShareModal}
                  showDeleteModal={showDeleteModal}
                  showDeleteAllModal={() => setShowDeleteAllModal(true)}
                />
              </div>
            </div>
          </div>

          <BlurBackground
            visible={!untoggled && (showHistorySidebar || toggledSidebar)}
          />

          <div
            ref={masterFlexboxRef}
            className="flex h-full w-full overflow-x-hidden"
          >
            <div className="flex h-full relative px-2 flex-col w-full">
              {documentSidebarInitialWidth !== undefined && isReady ? (
                <Dropzone onDrop={handleImageUpload} noClick>
                  {({ getRootProps }) => (
                    <div className="flex h-full w-full">
                      {!settings?.isMobile && (
                        <div
                          style={{ transition: "width 0.30s ease-out" }}
                          className={`
                          flex-none 
                          overflow-y-hidden 
                          bg-background-100 
                          transition-all 
                          bg-opacity-80
                          duration-300 
                          ease-in-out
                          h-full
                          ${toggledSidebar ? "w-[200px]" : "w-[0px]"}
                      `}
                        ></div>
                      )}

                      <div
                        className={`h-full w-full relative flex-auto transition-margin duration-300 overflow-x-auto mobile:pb-12 desktop:pb-[100px]`}
                        {...getRootProps()}
                      >
                        <div
                          className={`w-full h-[calc(100vh-160px)] flex default-scrollbar items-center justify-center relative`}
                          ref={scrollableDivRef}
                        >
                          {/* ChatBanner is a custom banner that displays a admin-specified message at 
                      the top of the chat page. Oly used in the EE version of the app. */}

                          <div className="h-[50%] my-auto bg-gradient-to-r from-blue-500 to-blue-900 rounded-xl w-[95%] flex flex-col justify-center items-center">
                            {/* <StarterMessages
                                  currentPersona={currentPersona}
                                  onSubmit={(messageOverride) =>
                                    onSubmit({
                                      messageOverride,
                                    })
                                  }
                                /> */}
                            <ChatInputBar
                              removeDocs={() => {
                                // clearSelectedDocuments();
                              }}
                              showDocs={() => {
                                setFiltersToggled(false);
                                setDocumentSidebarToggled(true);
                              }}
                              removeFilters={() => {
                                // filterManager.setSelectedSources([]);
                                // filterManager.setSelectedTags([]);
                                // filterManager.setSelectedDocumentSets([]);
                                setDocumentSidebarToggled(false);
                              }}
                              showConfigureAPIKey={() =>
                                setShowApiKeyModal(true)
                              }
                              chatState={"input"}
                              stopGenerating={stopGenerating}
                              openModelSettings={() => setSettingsToggled(true)}
                              selectedDocuments={[]}
                              // assistant stuff
                              selectedAssistant={liveAssistant}
                              setSelectedAssistant={onAssistantChange}
                              setAlternativeAssistant={setAlternativeAssistant}
                              alternativeAssistant={alternativeAssistant}
                              // end assistant stuff
                              message={message}
                              setMessage={setMessage}
                              onSubmit={onSubmit}
                              llmOverrideManager={llmOverrideManager}
                              files={currentMessageFiles}
                              setFiles={setCurrentMessageFiles}
                              toggleFilters={
                                retrievalEnabled ? toggleFilters : undefined
                              }
                              handleFileUpload={handleImageUpload}
                              textAreaRef={textAreaRef}
                              chatSessionId={chatSessionIdRef.current!}
                            />
                          </div>
                        </div>
                        <div
                          ref={inputRef}
                          className="absolute bottom-0 z-10 w-full"
                        >
                          <div className="w-[95%] mx-auto relative mb-8">
                            {aboveHorizon && (
                              <div className="pointer-events-none w-full bg-transparent flex sticky justify-center">
                                <button
                                  onClick={() => clientScrollToBottom()}
                                  className="p-1 pointer-events-auto rounded-2xl bg-background-strong border border-border mb-2 mx-auto "
                                >
                                  <FiArrowDown size={18} />
                                </button>
                              </div>
                            )}

                            {enterpriseSettings &&
                              enterpriseSettings.custom_lower_disclaimer_content && (
                                <div className="mobile:hidden mt-4 flex items-center justify-center relative w-[95%] mx-auto">
                                  <div className="text-sm text-text-500 max-w-searchbar-max px-4 text-center">
                                    <MinimalMarkdown
                                      content={
                                        enterpriseSettings.custom_lower_disclaimer_content
                                      }
                                    />
                                  </div>
                                </div>
                              )}
                            {enterpriseSettings &&
                              enterpriseSettings.use_custom_logotype && (
                                <div className="hidden lg:block absolute right-0 bottom-0">
                                  <img
                                    src="/api/enterprise-settings/logotype"
                                    alt="logotype"
                                    style={{ objectFit: "contain" }}
                                    className="w-fit h-8"
                                  />
                                </div>
                              )}
                          </div>
                        </div>
                      </div>
                      {!settings?.isMobile && (
                        <div
                          style={{ transition: "width 0.30s ease-out" }}
                          className={`
                          flex-none 
                          overflow-y-hidden 
                          transition-all 
                          duration-300 
                          ease-in-out
                          ${
                            documentSidebarToggled && retrievalEnabled
                              ? "w-[400px]"
                              : "w-[0px]"
                          }
                      `}
                        ></div>
                      )}
                    </div>
                  )}
                </Dropzone>
              ) : (
                <div className="mx-auto h-full flex">
                  <div
                    style={{ transition: "width 0.30s ease-out" }}
                    className={`flex-none bg-transparent transition-all bg-opacity-80 duration-300 epase-in-out h-full
                        ${
                          toggledSidebar && !settings?.isMobile
                            ? "w-[250px] "
                            : "w-[0px]"
                        }`}
                  />
                  <div className="my-auto">
                    <OnyxInitializingLoader />
                  </div>
                </div>
              )}
            </div>
          </div>
          <FixedLogo backgroundToggled={toggledSidebar || showHistorySidebar} />
        </div>
        <div className="fixed bottom-0 p-4 right-0">
          <div className="flex items-center justify-center gap-2">
            <p>Use Onyx as default for your new Tab</p>
            <Switch
              id="useOnyx"
              checked={useOnyxAsNewTab}
              onCheckedChange={handleUseOnyxToggle}
            />
          </div>
        </div>
      </div>
    </>
  );
}
