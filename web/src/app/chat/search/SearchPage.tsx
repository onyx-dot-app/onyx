"use client";

import {
  redirect,
  usePathname,
  useRouter,
  useSearchParams,
} from "next/navigation";
import {
  ChatFileType,
  ChatSessionSharedStatus,
  Message,
} from "@/app/chat/interfaces";

import Cookies from "js-cookie";
import { Persona } from "@/app/admin/assistants/interfaces";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import {
  buildLatestMessageChain,
  getHumanAndAIMessageFromMessageNumber,
  PacketType,
  personaIncludesRetrieval,
  removeMessage,
  updateParentChildren,
  useScrollonStream,
} from "@/app/chat/lib";
import {
  Dispatch,
  SetStateAction,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { usePopup } from "@/components/admin/connectors/Popup";
import { SEARCH_PARAM_NAMES } from "@/app/chat/searchParams";
import { useFilters, useLlmManager } from "@/lib/hooks";
import { ChatState, FeedbackType, RegenerationState } from "@/app/chat/types";
import { OnyxDocument } from "@/lib/search/interfaces";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import { useChatContext } from "@/components/context/ChatContext";
import { ChatPopup } from "@/app/chat/ChatPopup";
import { useSidebarVisibility } from "@/components/chat/hooks";
import {
  PRO_SEARCH_TOGGLED_COOKIE_NAME,
  SIDEBAR_TOGGLED_COOKIE_NAME,
} from "@/components/resizable/constants";
import FixedLogo from "@/components/logo/FixedLogo";

import {
  INTERNET_SEARCH_TOOL_ID,
  SEARCH_TOOL_ID,
} from "@/app/chat/tools/constants";
import { useUser } from "@/components/user/UserProvider";
import { ApiKeyModal } from "@/components/llm/ApiKeyModal";
import BlurBackground from "@/components/chat/BlurBackground";
import { NoAssistantModal } from "@/components/modals/NoAssistantModal";
import { useAssistants } from "@/components/context/AssistantsContext";
import TextView from "@/components/chat/TextView";
import { useSendMessageToParent } from "@/lib/extension/utils";
import { CHROME_MESSAGE } from "@/lib/extension/constants";

import { getSourceMetadata } from "@/lib/sources";
import { UserSettingsModal } from "@/app/chat/modal/UserSettingsModal";
import AssistantModal from "@/app/assistants/mine/AssistantModal";
import { useSidebarShortcut } from "@/lib/browserUtilities";

import { SourceMetadata } from "@/lib/search/interfaces";
import { ValidSources } from "@/lib/types";
import { ChatSearchModal } from "@/app/chat/chat_search/ChatSearchModal";
import { SearchInput } from "./components/SearchInput";
import { SearchFilters } from "./components/SearchFilters";
import { SearchResults } from "./components/SearchResults";
import { streamSearchWithCitation } from "./searchUtils";
import { UserDropdown } from "@/components/UserDropdown";
import { FiClock, FiUsers, FiFilter } from "react-icons/fi";
import { PageSelector } from "@/components/PageSelector";
import {
  FilterBox,
  SourceFilter,
  TimeFilter,
  AuthorFilter,
} from "./components/FilterBox";
import { MoreFiltersPopup } from "./components/MoreFiltersPopup";

const SYSTEM_MESSAGE_ID = -3;

export default function SearchPage({
  toggle,
  documentSidebarInitialWidth,
  sidebarVisible,
  firstMessage,
  isTransitioningFromChat,
}: {
  toggle: (toggled?: boolean) => void;
  documentSidebarInitialWidth?: number;
  sidebarVisible: boolean;
  firstMessage?: string;
  isTransitioningFromChat?: boolean;
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
    shouldShowWelcomeModal,
    refreshChatSessions,
    proSearchToggled,
    authors,
  } = useChatContext();

  const defaultAssistantIdRaw = searchParams?.get(
    SEARCH_PARAM_NAMES.PERSONA_ID
  );
  const defaultAssistantId = defaultAssistantIdRaw
    ? parseInt(defaultAssistantIdRaw)
    : undefined;

  const [hideUserDropdown, setHideUserDropdown] = useState(false);
  const [showUserSettingsModal, setShowUserSettingsModal] = useState(false);
  // Function declarations need to be outside of blocks in strict mode
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

  // handle redirect if chat page is disabled
  // NOTE: this must be done here, in a client component since
  // settings are passed in via Context and therefore aren't
  // available in server-side components
  const settings = useContext(SettingsContext);
  const enterpriseSettings = settings?.enterpriseSettings;

  const [viewingFilePicker, setViewingFilePicker] = useState(false);
  const [toggleDocSelection, setToggleDocSelection] = useState(false);
  const [documentSidebarVisible, setDocumentSidebarVisible] = useState(false);
  const [proSearchEnabled, setProSearchEnabled] = useState(proSearchToggled);
  const toggleProSearch = () => {
    Cookies.set(
      PRO_SEARCH_TOGGLED_COOKIE_NAME,
      String(!proSearchEnabled).toLocaleLowerCase()
    );
    setProSearchEnabled(!proSearchEnabled);
  };

  const isInitialLoad = useRef(true);
  const [userSettingsToggled, setUserSettingsToggled] = useState(false);

  const {
    assistants: availableAssistants,
    finalAssistants,
    pinnedAssistants,
  } = useAssistants();

  const [showApiKeyModal, setShowApiKeyModal] = useState(
    !shouldShowWelcomeModal
  );

  const { user, isAdmin } = useUser();
  const slackChatId = searchParams?.get("slackChatId");
  const existingChatIdRaw = searchParams?.get("chatId");

  const [showHistorySidebar, setShowHistorySidebar] = useState(false); // State to track if sidebar is open

  const existingChatSessionId = existingChatIdRaw ? existingChatIdRaw : null;

  const selectedChatSession = chatSessions.find(
    (chatSession) => chatSession.id === existingChatSessionId
  );

  useEffect(() => {
    if (user?.is_anonymous_user) {
      Cookies.set(
        SIDEBAR_TOGGLED_COOKIE_NAME,
        String(!sidebarVisible).toLocaleLowerCase()
      );
      toggle(false);
    }
  }, [user, sidebarVisible, toggle]);

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
  const search_param_temperature = searchParams?.get(
    SEARCH_PARAM_NAMES.TEMPERATURE
  );

  const defaultTemperature = search_param_temperature
    ? parseFloat(search_param_temperature)
    : selectedAssistant?.tools.some(
          (tool) =>
            tool.in_code_tool_id === SEARCH_TOOL_ID ||
            tool.in_code_tool_id === INTERNET_SEARCH_TOOL_ID
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

  const [alternativeAssistant, setAlternativeAssistant] =
    useState<Persona | null>(null);

  const [presentingDocument, setPresentingDocument] =
    useState<OnyxDocument | null>(null);

  // Current assistant is decided based on this ordering
  // 1. Alternative assistant (assistant selected explicitly by user)
  // 2. Selected assistant (assistnat default in this chat session)
  // 3. First pinned assistants (ordered list of pinned assistants)
  // 4. Available assistants (ordered list of available assistants)
  // Relevant test: `live_assistant.spec.ts`
  const liveAssistant: Persona | undefined = useMemo(
    () =>
      alternativeAssistant ||
      selectedAssistant ||
      pinnedAssistants[0] ||
      availableAssistants[0],
    [
      alternativeAssistant,
      selectedAssistant,
      pinnedAssistants,
      availableAssistants,
    ]
  );

  const llmManager = useLlmManager(
    llmProviders,
    selectedChatSession,
    liveAssistant
  );

  const noAssistants = liveAssistant == null || liveAssistant == undefined;

  const availableSources: ValidSources[] = useMemo(() => {
    return ccPairs.map((ccPair) => ccPair.source);
  }, [ccPairs]);

  const sources: SourceMetadata[] = useMemo(() => {
    const uniqueSources = Array.from(new Set(availableSources));
    return uniqueSources.map((source) => getSourceMetadata(source));
  }, [availableSources]);

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

  const [message, setMessage] = useState(
    searchParams?.get(SEARCH_PARAM_NAMES.USER_PROMPT) || ""
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

  const [submittedMessage, setSubmittedMessage] = useState(firstMessage || "");

  const [chatState, setChatState] = useState<Map<string | null, ChatState>>(
    new Map([[chatSessionIdRef.current, firstMessage ? "loading" : "input"]])
  );

  const [regenerationState, setRegenerationState] = useState<
    Map<string | null, RegenerationState | null>
  >(new Map([[null, null]]));

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

  const currentChatState = (): ChatState => {
    return chatState.get(currentSessionId()) || "input";
  };

  const currentChatAnswering = () => {
    return (
      currentChatState() == "toolBuilding" ||
      currentChatState() == "streaming" ||
      currentChatState() == "loading"
    );
  };

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

  const resetRegenerationState = (sessionId?: string | null) => {
    updateRegenerationState(null, sessionId);
  };

  const currentRegenerationState = (): RegenerationState | null => {
    return regenerationState.get(currentSessionId()) || null;
  };

  const [canContinue, setCanContinue] = useState<Map<string | null, boolean>>(
    new Map([[null, false]])
  );

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

  const currentCanContinue = (): boolean => {
    return canContinue.get(currentSessionId()) || false;
  };

  const currentSessionChatState = currentChatState();
  const currentSessionRegenerationState = currentRegenerationState();

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

  useEffect(() => {
    if (
      submittedMessage &&
      currentSessionChatState === "loading" &&
      messageHistory.length == 0
    ) {
      window.parent.postMessage(
        { type: CHROME_MESSAGE.LOAD_NEW_CHAT_PAGE },
        "*"
      );
    }
  }, [submittedMessage, currentSessionChatState, messageHistory.length]);
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
    fetchMaxTokens();
  }, [liveAssistant]);

  const filterManager = useFilters();
  const [isChatSearchModalOpen, setIsChatSearchModalOpen] = useState(false);

  const [currentFeedback, setCurrentFeedback] = useState<
    [FeedbackType, number] | null
  >(null);

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
      // If all messages are already rendered, scroll immediately
      endDivRef.current.scrollIntoView({
        behavior: fast ? "auto" : "smooth",
      });

      setHasPerformedInitialScroll(true);
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
    if (
      (!personaIncludesRetrieval &&
        (!selectedDocuments || selectedDocuments.length === 0) &&
        documentSidebarVisible) ||
      chatSessionIdRef.current == undefined
    ) {
      setDocumentSidebarVisible(false);
    }
    clientScrollToBottom();
  }, [chatSessionIdRef.current]);

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

  const [uncaughtError, setUncaughtError] = useState<string | null>(null);
  const [agenticGenerating, setAgenticGenerating] = useState(false);

  const autoScrollEnabled =
    (user?.preferences?.auto_scroll && !agenticGenerating) ?? false;

  useScrollonStream({
    chatState: currentSessionChatState,
    scrollableDivRef,
    scrollDist,
    endDivRef,
    debounceNumber,
    mobile: settings?.isMobile,
    enableAutoScroll: autoScrollEnabled,
  });

  // Track whether a message has been sent during this page load, keyed by chat session id
  const [sessionHasSentLocalUserMessage, setSessionHasSentLocalUserMessage] =
    useState<Map<string | null, boolean>>(new Map());

  // Update the local state for a session once the user sends a message
  const markSessionMessageSent = (sessionId: string | null) => {
    setSessionHasSentLocalUserMessage((prev) => {
      const newMap = new Map(prev);
      newMap.set(sessionId, true);
      return newMap;
    });
  };
  const currentSessionHasSentLocalUserMessage = useMemo(
    () => (sessionId: string | null) => {
      return sessionHasSentLocalUserMessage.size === 0
        ? undefined
        : sessionHasSentLocalUserMessage.get(sessionId) || false;
    },
    [sessionHasSentLocalUserMessage]
  );

  const { height: screenHeight } = useScreenSize();

  const getContainerHeight = useMemo(() => {
    return () => {
      if (!currentSessionHasSentLocalUserMessage(chatSessionIdRef.current)) {
        return undefined;
      }
      if (autoScrollEnabled) return undefined;

      if (screenHeight < 600) return "40vh";
      if (screenHeight < 1200) return "50vh";
      return "60vh";
    };
  }, [autoScrollEnabled, screenHeight, currentSessionHasSentLocalUserMessage]);

  // Used to maintain a "time out" for history sidebar so our existing refs can have time to process change
  const [untoggled, setUntoggled] = useState(false);

  const explicitlyUntoggle = () => {
    setShowHistorySidebar(false);

    setUntoggled(true);
    setTimeout(() => {
      setUntoggled(false);
    }, 200);
  };
  const toggleSidebar = () => {
    if (user?.is_anonymous_user) {
      return;
    }
    Cookies.set(
      SIDEBAR_TOGGLED_COOKIE_NAME,
      String(!sidebarVisible).toLocaleLowerCase()
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
    sidebarVisible,
    sidebarElementRef,
    showDocSidebar: showHistorySidebar,
    setShowDocSidebar: setShowHistorySidebar,
    setToggled: removeToggle,
    mobile: settings?.isMobile,
    isAnonymousUser: user?.is_anonymous_user,
  });

  // Virtualization + Scrolling related effects and functions
  const scrollInitialized = useRef(false);

  const imageFileInMessageHistory = useMemo(() => {
    return messageHistory
      .filter((message) => message.type === "user")
      .some((message) =>
        message.files.some((file) => file.type === ChatFileType.IMAGE)
      );
  }, [messageHistory]);

  useSendMessageToParent();

  useEffect(() => {
    if (liveAssistant) {
      const hasSearchTool = liveAssistant.tools.some(
        (tool) => tool.in_code_tool_id === SEARCH_TOOL_ID
      );
      setRetrievalEnabled(hasSearchTool);
      if (!hasSearchTool) {
        filterManager.clearFilters();
      }
    }
  }, [liveAssistant]);

  const [retrievalEnabled, setRetrievalEnabled] = useState(() => {
    if (liveAssistant) {
      return liveAssistant.tools.some(
        (tool) => tool.in_code_tool_id === SEARCH_TOOL_ID
      );
    }
    return false;
  });

  useEffect(() => {
    if (!retrievalEnabled) {
      setDocumentSidebarVisible(false);
    }
  }, [retrievalEnabled]);

  const innerSidebarElementRef = useRef<HTMLDivElement>(null);

  const [selectedDocuments, setSelectedDocuments] = useState<OnyxDocument[]>(
    []
  );
  useEffect(() => {
    llmManager.updateImageFilesPresent(imageFileInMessageHistory);
  }, [imageFileInMessageHistory]);

  const pathname = usePathname();
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

  const navigatingAway = useRef(false);
  // Keep a ref to abortControllers to ensure we always have the latest value
  const abortControllersRef = useRef(abortControllers);
  useEffect(() => {
    abortControllersRef.current = abortControllers;
  }, [abortControllers]);

  useSidebarShortcut(router, toggleSidebar);

  // New state for search UI
  const [searchQuery, setSearchQuery] = useState("");
  const [isSearching, setIsSearching] = useState(false);
  const [searchResults, setSearchResults] = useState<OnyxDocument[]>([]);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [selectedFilter, setSelectedFilter] = useState("all");
  const [sourceResults, setSourceResults] = useState<Record<string, number>>(
    {}
  );

  // Filter state management
  const [selectedAuthors, setSelectedAuthors] = useState<string[]>([]);

  const handleAuthorSelect = (author: string) => {
    setSelectedAuthors((prev) =>
      prev.includes(author)
        ? prev.filter((a) => a !== author)
        : [...prev, author]
    );
  };

  const handleSourceSelect = (source: SourceMetadata) => {
    const isSelected = filterManager.selectedSources.some(
      (s) => s.internalName === source.internalName
    );

    filterManager.setSelectedSources(
      isSelected
        ? filterManager.selectedSources.filter(
            (s) => s.internalName !== source.internalName
          )
        : [...filterManager.selectedSources, source]
    );

    if (searchQuery) {
      handleSearch(searchQuery);
    }
  };

  const handleTimeSelect = (
    range: { from: Date; to: Date; selectValue: string } | null
  ) => {
    filterManager.setTimeRange(range);
    if (searchQuery) {
      handleSearch(searchQuery);
    }
  };

  // Function to handle search using our new streamSearchWithCitation function
  const handleSearch = async (query: string) => {
    setFirstSearch(false);
    if (!query.trim() || !liveAssistant) return;

    setSearchQuery(query);
    setIsSearching(true);

    setSearchError(null);
    setSearchResults([]);
    setSourceResults({});

    try {
      for await (const response of streamSearchWithCitation({
        query,
        persona: liveAssistant,
        sources: filterManager.selectedSources,
        documentSets: filterManager.selectedDocumentSets,
        timeRange: filterManager.timeRange,
        tags: filterManager.selectedTags,
      })) {
        if (response.error) {
          setSearchError(response.error);
        }

        if (response.documents.length > 0) {
          setSearchResults(response.documents);
          console.log("searchResults", response.documents);

          // Count results by source type
          const counts: Record<string, number> = {};
          response.documents.forEach((doc) => {
            counts[doc.source_type] = (counts[doc.source_type] || 0) + 1;
          });
          setSourceResults(counts);
        }
      }
    } catch (error) {
      setSearchError(
        `An error occurred: ${
          error instanceof Error ? error.message : String(error)
        }`
      );
    } finally {
      setIsSearching(false);
    }
  };
  const [firstSearch, setFirstSearch] = useState(true);

  // Filter documents based on selected filter
  const filteredDocuments = useMemo(() => {
    if (selectedFilter === "all") {
      return searchResults;
    }
    return searchResults.filter((doc) => doc.source_type === selectedFilter);
  }, [searchResults, selectedFilter]);

  // Handle document click
  const handleDocumentClick = (document: OnyxDocument) => {
    console.log("document", document);
    if (document.link || document.document_id.startsWith("https://")) {
      window.open(document.link || document.document_id, "_blank");
    } else {
      setPresentingDocument(document);
      setDocumentSidebarVisible(true);
    }
  };
  const [showAssistantsModal, setShowAssistantsModal] = useState(false);

  // Add state for pagination
  const [currentPage, setCurrentPage] = useState(1);
  const resultsPerPage = 50;

  // Get paginated results
  const paginatedResults = useMemo(() => {
    const startIndex = (currentPage - 1) * resultsPerPage;
    return filteredDocuments.slice(startIndex, startIndex + resultsPerPage);
  }, [filteredDocuments, currentPage]);

  // Calculate total pages
  const totalPages = useMemo(() => {
    return Math.max(1, Math.ceil(filteredDocuments.length / resultsPerPage));
  }, [filteredDocuments]);

  // Handle page change
  const handlePageChange = (page: number) => {
    setCurrentPage(page);
    // Scroll to top of results
    document.querySelector(".search-results-container")?.scrollTo(0, 0);
  };

  // Add state to track transition
  const fromChat = searchParams?.get("fromChat") === "true";
  const queryParam = searchParams?.get("query");
  const [showInitialContent, setShowInitialContent] = useState(
    !isTransitioningFromChat
  );

  // Initialize search query from URL param if coming from chat and handle transition animation
  useEffect(() => {
    if (isTransitioningFromChat) {
      const timer = setTimeout(() => {
        setShowInitialContent(true);
      }, 1000);

      return () => clearTimeout(timer);
    }
  }, [fromChat, queryParam, isTransitioningFromChat]);

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

      {/* Assistants modal- browse, creat, etc. */}
      {showAssistantsModal && (
        <AssistantModal hideModal={() => setShowAssistantsModal(false)} />
      )}

      <ChatSearchModal
        open={isChatSearchModalOpen}
        onCloseModal={() => setIsChatSearchModalOpen(false)}
      />

      {presentingDocument && (
        <TextView
          presentingDocument={presentingDocument}
          onClose={() => setPresentingDocument(null)}
        />
      )}

      <div className="fixed inset-0 flex flex-col text-text-dark">
        <div className="h-[100dvh] overflow-y-hidden">
          <BlurBackground
            visible={!untoggled && (showHistorySidebar || sidebarVisible)}
            onClick={() => toggleSidebar()}
          />

          <div
            ref={masterFlexboxRef}
            className="flex h-full w-full overflow-x-hidden"
          >
            <div className="flex pb-12   md:mt-0 flex-col h-full w-full">
              {/* Header with search input */}
              {!firstSearch && (
                <div className="flex-none w-full flex justify-center p-4 border-b border-background-200">
                  <SearchInput
                    // hide={firstSearch}
                    onSearch={handleSearch}
                    initialQuery={searchQuery}
                    placeholder="Find knowledge at your enterprise..."
                    isMiddle={false}
                    // isAnimatingFromChatInitial={isTransitioningFromChat}
                  />
                </div>
              )}

              {/* Main content area */}
              <div className="flex-grow overflow-hidden">
                {searchQuery ? (
                  <div className="overflow-y-auto max-w-3xl w-[95%]  md:max-w-4xl flex relative mx-auto ">
                    {/* Filters */}
                    <div className="flex w-full h-screen relative">
                      {/* Results - scrollable and with max width */}
                      <div className="w-full h-full overflow-y-auto max-w-3xl pr-4">
                        <div className="search-results-container">
                          <SearchResults
                            documents={paginatedResults}
                            onDocumentClick={handleDocumentClick}
                            isLoading={
                              isSearching && searchResults.length === 0
                            }
                          />
                        </div>

                        {/* Pagination */}
                        {filteredDocuments.length > 0 && (
                          <div className="flex justify-center py-8 border-t border-gray-100 mt-6">
                            <PageSelector
                              currentPage={currentPage}
                              totalPages={totalPages}
                              onPageChange={handlePageChange}
                              shouldScroll={true}
                            />
                          </div>
                        )}
                      </div>

                      {/* Filters - sticky on scroll */}
                      <div className="w-72 ml-4 sticky top-24 mt-4">
                        <SearchFilters
                          totalResults={searchResults.length}
                          selectedSources={
                            filterManager.selectedSources.length > 0
                              ? filterManager.selectedSources.map(
                                  (source) => source.internalName
                                )
                              : ["all"]
                          }
                          setSelectedSources={(sourceNames) => {
                            // If "all" is selected, clear all source filters
                            if (sourceNames.includes("all")) {
                              filterManager.setSelectedSources([]);
                              return;
                            }

                            // Convert source names back to SourceMetadata objects
                            const sourceMetadataArray = sourceNames
                              .map((sourceName) => {
                                // Find the corresponding source metadata from available sources
                                const sourceMetadata = sources.find(
                                  (s) => s.internalName === sourceName
                                );

                                // If found, return the full source metadata object
                                return sourceMetadata as SourceMetadata;
                              })
                              .filter(Boolean) as SourceMetadata[];

                            filterManager.setSelectedSources(
                              sourceMetadataArray
                            );
                          }}
                          availableSources={sources}
                          sourceResults={sourceResults}
                          filterManager={filterManager}
                          availableDocumentSets={documentSets}
                          availableTags={tags}
                        />
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="flex flex-col pb-12 items-center justify-center h-full">
                    <div className="text-center max-w-2xl w-full px-4">
                      <h2
                        className={`text-3xl font-semibold mb-4 transition-opacity duration-500 ${
                          showInitialContent ? "opacity-100" : "opacity-0"
                        }`}
                      >
                        Find knowledge across your enterprise
                      </h2>
                      <p
                        className={`text-text-500 mb-8 text-lg transition-opacity duration-500 ${
                          showInitialContent ? "opacity-100" : "opacity-0"
                        }`}
                      >
                        Search across all your connected sources to find the
                        information you need.
                      </p>

                      {/* Add search input to initial landing page */}
                      <div className="mb-8 w-full mx-auto">
                        <SearchInput
                          onSearch={handleSearch}
                          initialQuery={queryParam || ""}
                          placeholder="Find knowledge at your enterprise..."
                          isMiddle={true}
                          isAnimatingFromChatInitial={isTransitioningFromChat}
                        />
                      </div>

                      {/* Filter boxes BELOW the search input */}
                      <div
                        className={`flex w-full grid grid-cols-4 mt-6 gap-x-12 flex-nowrap transition-opacity duration-500 ${
                          showInitialContent ? "opacity-100" : "opacity-0"
                        }`}
                      >
                        <FilterBox
                          label="Source"
                          icon={<FiFilter className="h-4 w-4" />}
                          selected={filterManager.selectedSources.length > 0}
                          count={
                            filterManager.selectedSources.length || undefined
                          }
                          contentComponent={
                            <SourceFilter
                              sources={sources}
                              selectedSources={filterManager.selectedSources}
                              onSourceSelect={handleSourceSelect}
                            />
                          }
                        />

                        <FilterBox
                          label="Time Range"
                          icon={<FiClock className="h-4 w-4" />}
                          selected={filterManager.timeRange !== null}
                          contentComponent={
                            <TimeFilter
                              selectedTimeRange={filterManager.timeRange}
                              onTimeSelect={handleTimeSelect}
                            />
                          }
                        />

                        {authors && authors.length > 0 && (
                          <FilterBox
                            label="Author"
                            icon={<FiUsers className="h-4 w-4" />}
                            selected={selectedAuthors.length > 0}
                            count={selectedAuthors.length || undefined}
                            contentComponent={
                              <AuthorFilter
                                authors={authors}
                                selectedAuthors={selectedAuthors}
                                onAuthorSelect={handleAuthorSelect}
                              />
                            }
                          />
                        )}

                        {tags.length > 0 ||
                          (documentSets.length > 0 && (
                            <FilterBox
                              label="More Filters"
                              icon={<FiFilter className="h-4 w-4" />}
                              selected={
                                filterManager.selectedDocumentSets.length > 0 ||
                                filterManager.selectedTags.length > 0
                              }
                              count={
                                filterManager.selectedDocumentSets.length +
                                  filterManager.selectedTags.length || undefined
                              }
                              contentComponent={
                                <MoreFiltersPopup
                                  filterManager={filterManager}
                                  availableSources={sources}
                                  availableDocumentSets={documentSets}
                                  availableTags={tags}
                                  trigger={<></>}
                                />
                              }
                            />
                          ))}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
          <FixedLogo backgroundToggled={sidebarVisible || showHistorySidebar} />
          {showUserSettingsModal && (
            <UserSettingsModal
              setPopup={setPopup}
              setCurrentLlm={(newLlm) => llmManager.updateCurrentLlm(newLlm)}
              defaultModel={user?.preferences.default_model!}
              llmProviders={llmProviders}
              onClose={() => {
                setShowUserSettingsModal(false);
              }}
            />
          )}

          <div className="fixed right-4 top-4">
            <UserDropdown
              toggleUserSettings={() => {
                setShowUserSettingsModal(true);
              }}
              hideUserDropdown={hideUserDropdown}
            />
          </div>
        </div>
      </div>
    </>
  );
}
