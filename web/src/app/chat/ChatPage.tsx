"use client";

import {
  useRouter,
  useSearchParams,
  usePathname,
  redirect,
} from "next/navigation";
import {
  ChatFileType,
  ChatSession,
  ChatSessionSharedStatus,
  FileDescriptor,
  Message,
} from "./interfaces";

import Prism from "prismjs";
import Cookies from "js-cookie";
import { HistorySidebar } from "./sessionSidebar/HistorySidebar";
import { Persona } from "../admin/assistants/interfaces";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import {
  buildChatUrl,
  buildLatestMessageChain,
  createChatSession,
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
  SendMessageParams,
  setMessageAsLatest,
  updateParentChildren,
  useScrollonStream,
} from "./lib";
import {
  Dispatch,
  SetStateAction,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  useReducer,
} from "react";
import { usePopup } from "@/components/admin/connectors/Popup";
import { SEARCH_PARAM_NAMES, shouldSubmitOnLoad } from "./searchParams";
import { LlmDescriptor, useFilters, useLlmManager } from "@/lib/hooks";
import { ChatState, FeedbackType, RegenerationState } from "./types";
import { DocumentResults } from "./documentSidebar/DocumentResults";
import { OnyxInitializingLoader } from "@/components/OnyxInitializingLoader";
import { FeedbackModal } from "./modal/FeedbackModal";
import { ShareChatSessionModal } from "./modal/ShareChatSessionModal";
import { FiArrowDown } from "react-icons/fi";
import { ChatIntro } from "./ChatIntro";
import { AIMessage, HumanMessage } from "./message/Messages";
import { StarterMessages } from "../../components/assistants/StarterMessage";
import {
  AnswerPiecePacket,
  OnyxDocument,
  DocumentInfoPacket,
  StreamStopInfo,
  StreamStopReason,
  SubQueryPiece,
  SubQuestionPiece,
  AgentAnswerPiece,
  RefinedAnswerImprovement,
  MinimalOnyxDocument,
} from "@/lib/search/interfaces";
import { buildFilters } from "@/lib/search/utils";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import Dropzone from "react-dropzone";
import { getFinalLLM, modelSupportsImageInput } from "@/lib/llm/utils";
import { ChatInputBar } from "./input/ChatInputBar";
import { useChatContext } from "@/components/context/ChatContext";
import { ChatPopup } from "./ChatPopup";
import FunctionalHeader from "@/components/chat/Header";

import {
  PRO_SEARCH_TOGGLED_COOKIE_NAME,
  SIDEBAR_TOGGLED_COOKIE_NAME,
} from "@/components/resizable/constants";
import FixedLogo from "@/components/logo/FixedLogo";
import ExceptionTraceModal from "@/components/modals/ExceptionTraceModal";
import { SEARCH_TOOL_ID } from "./tools/constants";
import { useUser } from "@/components/user/UserProvider";
import { ApiKeyModal } from "@/components/llm/ApiKeyModal";
import BlurBackground from "../../components/chat/BlurBackground";
import { NoAssistantModal } from "@/components/modals/NoAssistantModal";

import TextView from "@/components/chat/TextView";
import { Modal } from "@/components/Modal";
import { useSendMessageToParent } from "@/lib/extension/utils";
import {
  CHROME_MESSAGE,
  SUBMIT_MESSAGE_TYPES,
} from "@/lib/extension/constants";

import { getSourceMetadata } from "@/lib/sources";
import { UserSettingsModal } from "./modal/UserSettingsModal";
import { AgenticMessage } from "./message/AgenticMessage";
import AssistantModal from "../assistants/mine/AssistantModal";
import { useSidebarShortcut } from "@/lib/browserUtilities";
import { FilePickerModal } from "./my-documents/components/FilePicker";
import { useChatState } from "./hooks/useChatState";
import { useMessageSubmission } from "./hooks/useMessageSubmission";
import { useModal } from "./hooks/useModal";
import { useInitialSessionFetch } from "./hooks/useInitialSessionFetch";
import { useScreenSize, useSlackChatRedirect } from "./hooks/useUIUtils";
import { useAssistantManagement } from "./hooks/useAssistantManagement";
import { useScrollManagement } from "./hooks/useScrollManagement";
import { useSidebarManagement } from "./hooks/useSidebarManagement";
import { useDocumentManagement } from "./hooks/useDocumentManagement";
import { ModalRenderer } from "./components/ModalRenderer";

import { SourceMetadata } from "@/lib/search/interfaces";
import { ValidSources } from "@/lib/types";
import {
  FileResponse,
  FolderResponse,
  useDocumentsContext,
} from "./my-documents/DocumentsContext";
import { ChatSearchModal } from "./chat_search/ChatSearchModal";
import { ErrorBanner } from "./message/Resubmit";
import MinimalMarkdown from "@/components/chat/MinimalMarkdown";
import { WelcomeModal } from "@/components/initialSetup/welcome/WelcomeModal";

const TEMP_USER_MESSAGE_ID = -1;
const TEMP_ASSISTANT_MESSAGE_ID = -2;
const SYSTEM_MESSAGE_ID = -3;

export enum UploadIntent {
  ATTACH_TO_MESSAGE, // For files uploaded via ChatInputBar (paste, drag/drop)
  ADD_TO_DOCUMENTS, // For files uploaded via FilePickerModal or similar (just add to repo)
}

export function ChatPage({
  toggle,
  documentSidebarInitialWidth,
  sidebarVisible,
  firstMessage,
  initialFolders,
  initialFiles,
}: {
  toggle: (toggled?: boolean) => void;
  documentSidebarInitialWidth?: number;
  sidebarVisible: boolean;
  firstMessage?: string;
  initialFolders?: any;
  initialFiles?: any;
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
  } = useChatContext();

  const {
    selectedFiles,
    selectedFolders,
    addSelectedFile,
    addSelectedFolder,
    clearSelectedItems,
    setSelectedFiles,
    folders: userFolders,
    files: allUserFiles,
    uploadFile,
    currentMessageFiles,
    setCurrentMessageFiles,
  } = useDocumentsContext();

  const defaultAssistantIdRaw = searchParams?.get(
    SEARCH_PARAM_NAMES.PERSONA_ID
  );
  const defaultAssistantId = defaultAssistantIdRaw
    ? parseInt(defaultAssistantIdRaw)
    : undefined;

  // handle redirect if chat page is disabled
  // NOTE: this must be done here, in a client component since
  // settings are passed in via Context and therefore aren't
  // available in server-side components
  const settings = useContext(SettingsContext);
  const enterpriseSettings = settings?.enterpriseSettings;

  // IN PROGRESS: Centralized modal state management
  const { state: modalState, actions: modalActions } = useModal();

  // UI STATE: Document selection modal visibility
  const [isDocSelectionModalOpen, setIsDocSelectionModalOpen] = useState(false);
  // UI STATE: Pro search feature toggle state
  const [proSearchEnabled, setProSearchEnabled] = useState(proSearchToggled);
  const toggleProSearch = useCallback(() => {
    Cookies.set(
      PRO_SEARCH_TOGGLED_COOKIE_NAME,
      String(!proSearchEnabled).toLocaleLowerCase()
    );
    setProSearchEnabled(!proSearchEnabled);
  }, [proSearchEnabled]);

  const isInitialLoad = useRef(true);
  // UI STATE: User settings modal visibility
  const [isUserSettingsModalOpen, setIsUserSettingsModalOpen] = useState(false);

  // UI STATE: API key configuration modal visibility
  // const [isApiKeyModalOpen, setIsApiKeyModalOpen] = useState(
  //   !shouldShowWelcomeModal
  // );
  // REMOVED: Now handled by centralized modal management. Initially open if welcome modal is not shown. See `useEffect` near Popup.

  const { user, isAdmin } = useUser();
  const existingChatIdRaw = searchParams?.get("chatId");

  const existingChatSessionId = existingChatIdRaw ? existingChatIdRaw : null;

  const selectedChatSession = chatSessions.find(
    (chatSession) => chatSession.id === existingChatSessionId
  );

  // UI EFFECT: Hide sidebar for anonymous users
  useEffect(() => {
    if (user?.is_anonymous_user) {
      Cookies.set(
        SIDEBAR_TOGGLED_COOKIE_NAME,
        String(!sidebarVisible).toLocaleLowerCase()
      );
      toggle(false);
    }
  }, [user]);

  const chatSessionIdRef = useRef<string | null>(existingChatSessionId);

  // Only updates on session load (ie. rename / switching chat session)
  // Useful for determining which session has been loaded (i.e. still on `new, empty session` or `previous session`)
  const loadedIdSessionRef = useRef<string | null>(existingChatSessionId);

  // --- Assistant Management ---
  const existingChatSessionAssistantId = selectedChatSession?.persona_id;
  const {
    selectedAssistant,
    setSelectedAssistant,
    setSelectedAssistantFromId,
    alternativeAssistant,
    setAlternativeAssistant,
    liveAssistant,
    noAssistants,
    alternativeGeneratingAssistant,
    setAlternativeGeneratingAssistant,
    availableAssistants,
    pinnedAssistants,
  } = useAssistantManagement({
    existingChatSessionAssistantId,
    defaultAssistantId,
  });

  // --- End Assistant Management ---

  // --- Sidebar Management ---
  const {
    showHistorySidebar,
    setShowHistorySidebar,
    documentSidebarVisible,
    setDocumentSidebarVisible,
    untoggled,
    sidebarElementRef,
    explicitlyUntoggle,
    toggleSidebar,
    removeToggle,
    toggleDocumentSidebar,
  } = useSidebarManagement({
    sidebarVisible,
    toggle,
    user,
    settings,
  });

  const llmManager = useLlmManager(
    llmProviders,
    selectedChatSession,
    liveAssistant
  );

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

  // --- Document Management ---
  const {
    presentingDocument,
    setPresentingDocument,
    selectedDocuments,
    setSelectedDocuments,
    selectedDocumentTokens,
    setSelectedDocumentTokens,
    masterFlexboxRef,
    maxDocumentSidebarWidth,
    adjustDocumentSidebarWidth,
    clearSelectedDocuments,
    toggleDocumentSelection,
  } = useDocumentManagement({ maxTokens });

  const availableSources: ValidSources[] = useMemo(() => {
    return ccPairs.map((ccPair) => ccPair.source);
  }, [ccPairs]);

  const sources: SourceMetadata[] = useMemo(() => {
    const uniqueSources = Array.from(new Set(availableSources));
    return uniqueSources.map((source) => getSourceMetadata(source));
  }, [availableSources]);

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

  const [isReady, setIsReady] = useState(false);

  useEffect(() => {
    Prism.highlightAll();
    setIsReady(true);
  }, []);

  useEffect(() => {
    const userFolderId = searchParams?.get(SEARCH_PARAM_NAMES.USER_FOLDER_ID);
    const allMyDocuments = searchParams?.get(
      SEARCH_PARAM_NAMES.ALL_MY_DOCUMENTS
    );

    if (userFolderId) {
      const userFolder = userFolders.find(
        (folder) => folder.id === parseInt(userFolderId)
      );
      if (userFolder) {
        addSelectedFolder(userFolder);
      }
    } else if (allMyDocuments === "true" || allMyDocuments === "1") {
      // Clear any previously selected folders

      clearSelectedItems();

      // Add all user folders to the current context
      userFolders.forEach((folder) => {
        addSelectedFolder(folder);
      });
    }
  }, [
    userFolders,
    searchParams?.get(SEARCH_PARAM_NAMES.USER_FOLDER_ID),
    searchParams?.get(SEARCH_PARAM_NAMES.ALL_MY_DOCUMENTS),
    addSelectedFolder,
    clearSelectedItems,
  ]);

  const [message, setMessage] = useState(
    searchParams?.get(SEARCH_PARAM_NAMES.USER_PROMPT) || ""
  );

  const currentMessageMap = (
    messageDetail: Map<string | null, Map<number, Message>>
  ) => {
    return (
      messageDetail.get(chatSessionIdRef.current) || new Map<number, Message>()
    );
  };
  const getCurrentSessionId = (): string => {
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
    // and result in weird behavior
    completeMessageMapOverride?: Map<number, Message> | null;
    chatSessionId?: string;
    replacementsMap?: Map<number, number> | null;
    makeLatestChildMessage?: boolean;
  }) => {
    // deep copy
    const frozenCompleteMessageMap =
      completeMessageMapOverride || currentMessageMap(completeMessageDetail);
    const newCompleteMessageMap = structuredClone(frozenCompleteMessageMap);

    if (messages[0] !== undefined && newCompleteMessageMap.size === 0) {
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
      if (messages[0] !== undefined && latestMessage) {
        newCompleteMessageMap.get(
          latestMessage.messageId
        )!.latestChildMessageId = messages[0].messageId;
      }
    }

    const newCompleteMessageDetail = {
      sessionId: chatSessionId || getCurrentSessionId(),
      messageMap: newCompleteMessageMap,
    };

    updateCompleteMessageDetail(
      chatSessionId || getCurrentSessionId(),
      newCompleteMessageMap
    );
    console.log(newCompleteMessageDetail);
    return newCompleteMessageDetail;
  };

  const messageHistory = buildLatestMessageChain(
    currentMessageMap(completeMessageDetail)
  );

  const [submittedMessage, setSubmittedMessage] = useState(firstMessage || "");

  // Chat state management hook
  const {
    chatState,
    regenerationState,
    abortControllers,
    canContinue,
    getCurrentChatState,
    getCurrentRegenerationState,
    getCurrentCanContinue,
    getCurrentChatAnswering,
    updateChatState,
    updateRegenerationState,
    updateCanContinue,
    resetRegenerationState,
    updateStatesWithNewSessionId: updateChatStatesWithNewSessionId,
    setAbortControllers,
  } = useChatState(getCurrentSessionId, firstMessage);

  // Updates "null" session values to new session id for
  // regeneration, chat, and abort controller state, messagehistory
  // Extended updateStatesWithNewSessionId to include message detail updates
  const updateStatesWithNewSessionId = (newSessionId: string) => {
    // Update chat states
    updateChatStatesWithNewSessionId(newSessionId);

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

  const currentSessionChatState = getCurrentChatState();
  const currentSessionRegenerationState = getCurrentRegenerationState();

  // for document display
  // NOTE: -1 is a special designation that means the latest AI message
  // UI STATE: Selected message for document display (determines which message's documents are shown in sidebar)
  const [selectedMessageForDocDisplay, setSelectedMessageForDocDisplay] =
    useState<number | null>(null);

  const { aiMessage, humanMessage } = selectedMessageForDocDisplay
    ? getHumanAndAIMessageFromMessageNumber(
        messageHistory,
        selectedMessageForDocDisplay
      )
    : { aiMessage: null, humanMessage: null };

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
  }, [submittedMessage, currentSessionChatState]);

  const filterManager = useFilters();
  // UI STATE: Chat search modal visibility (for searching through chat history)
  const [isChatSearchModalOpen, setIsChatSearchModalOpen] = useState(false);

  // UI STATE: Feedback modal - currently active feedback form for a specific message
  const [currentFeedback, setCurrentFeedback] = useState<
    [FeedbackType, number] | null
  >(null);

  // UI STATE: Chat sharing modal visibility (for sharing chat sessions)
  const [isSharingModalOpen, setIsSharingModalOpen] = useState<boolean>(false);

  // UI STATE: Scroll position indicator - whether user has scrolled above the "horizon" (shows scroll-to-bottom button)
  const [aboveHorizon, setAboveHorizon] = useState(false);

  // UI STATE: Agentic generation indicator (shows when AI is using multi-step reasoning)
  const [agenticGenerating, setAgenticGenerating] = useState(false);

  const autoScrollEnabled =
    (user?.preferences?.auto_scroll && !agenticGenerating) ?? false;

  // --- Scroll Management ---
  const {
    scrollableDivRef,
    lastMessageRef,
    inputRef,
    endDivRef,
    endPaddingRef,
    waitForScrollRef,
    scrollDist,
    handleInputResize,
    clientScrollToBottom,
  } = useScrollManagement({ autoScrollEnabled });

  // UI CONSTANT: Debounce time for scroll events (milliseconds)
  const debounceNumber = 100; // time for debouncing

  // UI STATE: Initial scroll completion flag (prevents scroll issues during initial load)
  const [hasPerformedInitialScroll, setHasPerformedInitialScroll] = useState(
    existingChatSessionId === null
  );

  // UI REF: Text area reference for focus management and resizing
  const textAreaRef = useRef<HTMLTextAreaElement>(null);
  // UI EFFECT: Handle text area resizing when message content changes
  useEffect(() => {
    handleInputResize();
  }, [message]);

  // UI EFFECT: Auto-hide document sidebar when no documents are selected or retrieval is disabled
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

  const processSearchParamsAndSubmitMessage = (searchParamsString: string) => {
    const newSearchParams = new URLSearchParams(searchParamsString);
    const message = newSearchParams?.get("user-prompt");

    filterManager.buildFiltersFromQueryString(
      newSearchParams.toString(),
      availableSources,
      documentSets.map((ds) => ds.name),
      tags
    );

    const fileDescriptorString = newSearchParams?.get(SEARCH_PARAM_NAMES.FILES);
    const overrideFileDescriptors: FileDescriptor[] = fileDescriptorString
      ? JSON.parse(decodeURIComponent(fileDescriptorString))
      : [];

    newSearchParams.delete(SEARCH_PARAM_NAMES.SEND_ON_LOAD);

    router.replace(`?${newSearchParams.toString()}`, { scroll: false });

    // If there's a message, submit it
    if (message) {
      setSubmittedMessage(message);
      onSubmit({ messageOverride: message, overrideFileDescriptors });
    }
  };

  const loadNewPageLogic = (event: MessageEvent) => {
    if (event.data.type === SUBMIT_MESSAGE_TYPES.PAGE_CHANGE) {
      try {
        const url = new URL(event.data.href);
        processSearchParamsAndSubmitMessage(url.searchParams.toString());
      } catch (error) {
        console.error("Error parsing URL:", error);
      }
    }
  };

  // Equivalent to `loadNewPageLogic`
  useEffect(() => {
    if (searchParams?.get(SEARCH_PARAM_NAMES.SEND_ON_LOAD)) {
      processSearchParamsAndSubmitMessage(searchParams.toString());
    }
  }, [searchParams, router]);

  // UI EFFECT: Setup responsive document sidebar width and window event listeners
  useEffect(() => {
    adjustDocumentSidebarWidth();
    window.addEventListener("resize", adjustDocumentSidebarWidth);
    window.addEventListener("message", loadNewPageLogic);

    return () => {
      window.removeEventListener("message", loadNewPageLogic);
      window.removeEventListener("resize", adjustDocumentSidebarWidth);
    };
  }, []);

  if (!documentSidebarInitialWidth && maxDocumentSidebarWidth) {
    documentSidebarInitialWidth = Math.min(700, maxDocumentSidebarWidth);
  }

  const [uncaughtError, setUncaughtError] = useState<string | null>(null);

  const continueGenerating = () => {
    onSubmit({
      messageOverride:
        "Continue Generating (pick up exactly where you left off)",
    });
  };

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

  // UI FUNCTION: Calculate responsive container height based on screen size and auto-scroll state
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

  const reset = () => {
    setMessage("");
    setCurrentMessageFiles([]);
    clearSelectedItems();
    setLoadingError(null);
  };

  const onFeedback = async (
    messageId: number,
    feedbackType: FeedbackType,
    feedbackDetails: string,
    predefinedFeedback: string | undefined
  ) => {
    if (chatSessionIdRef.current === null) {
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

  const handleMessageSpecificFileUpload = async (acceptedFiles: File[]) => {
    const [_, llmModel] = getFinalLLM(
      llmProviders,
      liveAssistant ?? null,
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

    updateChatState("uploading", getCurrentSessionId());

    for (let file of acceptedFiles) {
      const formData = new FormData();
      formData.append("files", file);
      const response: FileResponse[] = await uploadFile(formData, null);

      if (response.length > 0 && response[0] !== undefined) {
        const uploadedFile = response[0];

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
      } else {
        setPopup({
          type: "error",
          message: "Failed to upload file",
        });
      }
    }

    updateChatState("input", getCurrentSessionId());
  };

  // UI STATE: Loading error message display
  const [loadingError, setLoadingError] = useState<string | null>(null);

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

  // ** Features gated on existence and properties of liveAssistant
  useEffect(() => {
    if (liveAssistant) {
      const hasSearchTool = liveAssistant.tools.some(
        (tool) =>
          tool.in_code_tool_id === SEARCH_TOOL_ID &&
          liveAssistant.user_file_ids?.length == 0 &&
          liveAssistant.user_folder_ids?.length == 0
      );
      setRetrievalEnabled(hasSearchTool);
      if (!hasSearchTool) {
        filterManager.clearFilters();
      }
    }
  }, [liveAssistant]);

  // UI STATE: Retrieval feature availability (controls document search and sidebar functionality)
  const [retrievalEnabled, setRetrievalEnabled] = useState(() => {
    if (liveAssistant) {
      return liveAssistant.tools.some(
        (tool) =>
          tool.in_code_tool_id === SEARCH_TOOL_ID &&
          liveAssistant.user_file_ids?.length == 0 &&
          liveAssistant.user_folder_ids?.length == 0
      );
    }
    return false;
  });
  // ** End Features gated on existence and properties of liveAssistant

  // UI EFFECT: Hide document sidebar when retrieval is disabled
  useEffect(() => {
    if (!retrievalEnabled) {
      setDocumentSidebarVisible(false);
    }
  }, [retrievalEnabled]);

  // UI STATE: Stack trace modal content (for displaying error details)
  // existence of this state is used to determine if the modal should be displayed
  const [stackTraceModalContent, setStackTraceModalContent] = useState<
    string | null
  >(null);

  // UI REF: Inner sidebar element for document results display
  const innerSidebarElementRef = useRef<HTMLDivElement>(null);
  // UI STATE: Settings modal visibility (general settings, not user-specific)
  const [isSettingsModalOpen, setIsSettingsModalOpen] = useState(false);

  const currentPersona = alternativeAssistant || liveAssistant;

  // UI CONSTANT: Distance threshold for showing scroll-to-bottom button
  const HORIZON_DISTANCE = 800;
  // UI FUNCTION: Handle scroll events to determine if scroll-to-bottom button should be shown
  const handleScroll = useCallback(() => {
    const scrollDistance =
      endDivRef?.current?.getBoundingClientRect()?.top! -
      inputRef?.current?.getBoundingClientRect()?.top!;
    scrollDist.current = scrollDistance;
    setAboveHorizon(scrollDist.current > HORIZON_DISTANCE);
  }, []);

  // slack chat redirect wuz here
  useSlackChatRedirect(
    (_error) =>
      setPopup({
        message: "Failed to load chat from Slack",
        type: "error",
      }),
    (isLoading: boolean) => {
      setIsReady(!isLoading);
    }
  );

  useEffect(() => {
    llmManager.updateImageFilesPresent(imageFileInMessageHistory);
  }, [imageFileInMessageHistory]);

  const pathname = usePathname();
  useEffect(() => {
    return () => {
      // Cleanup which only runs when the component unmounts (i.e. when you navigate away).
      const currentSession = getCurrentSessionId();
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

  // UI FUNCTION: Reset input bar state and styling after message submission
  const resetInputBar = () => {
    setMessage("");
    setCurrentMessageFiles([]);

    // Reset selectedFiles if they're under the context limit, but preserve selectedFolders.
    // If under the context limit, the files will be included in the chat history
    // so we don't need to keep them around.
    if (selectedDocumentTokens < maxTokens) {
      setSelectedFiles([]);
    }

    if (endPaddingRef.current) {
      endPaddingRef.current.style.height = `95px`;
    }
  };

  // Moved all submission logic to new service layer, accessed via useMessageSubmission hook
  // We can pass in the dependencies to the hook for now, which keeps this file cleaner, and
  // in the future we can add better state management/ abstractions to remove the need for these props
  const messageSubmissionDependencies = {
    // Session management
    liveAssistant,
    searchParams,
    llmManager,
    chatSessionIdRef,
    updateStatesWithNewSessionId,
    setAbortControllers,

    // Message preprocessing
    currentMessageMap,
    completeMessageDetail,
    updateCompleteMessageDetail,
    messageHistory,
    setPopup,
    getCurrentChatState,
    setAlternativeGeneratingAssistant,
    clientScrollToBottom,
    resetInputBar,

    // Streaming processing
    updateChatState,
    setAgenticGenerating,
    updateCanContinue,
    upsertToCompleteMessageMap,
    setSelectedMessageForDocDisplay,
    setUncaughtError,
    setSubmittedMessage,

    // Post processing
    resetRegenerationState,
    refreshChatSessions,
    router,
    pathname,
    navigatingAway,

    // Other dependencies
    alternativeAssistant,
    message,
    currentMessageFiles,
    selectedDocuments,
    selectedFolders,
    selectedFiles,
    filterManager,
    availableSources,
    documentSets,
    tags,
    settings,
    proSearchEnabled,
    retrievalEnabled,
    updateRegenerationState,
    markSessionMessageSent,
    setLoadingError,
    getCurrentSessionId,
  };

  const { submitMessage } = useMessageSubmission(messageSubmissionDependencies);

  // Using wrapper for now to avoid renaming uses and possibly breaking other code/ increasing scope
  const onSubmit = submitMessage;

  // Keep a ref to abortControllers to ensure we always have the latest value
  const abortControllersRef = useRef(abortControllers);
  useEffect(() => {
    abortControllersRef.current = abortControllers;
  }, [abortControllers]);
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

  useSidebarShortcut(router, toggleSidebar);

  // UI STATE: Shared chat session modal - currently displayed chat session for sharing
  // existence of this state is used to determine if the modal should be displayed
  const [sharedChatSession, setSharedChatSession] =
    useState<ChatSession | null>();

  const handleResubmitLastMessage = () => {
    // Grab the last user-type message
    const lastUserMsg = messageHistory
      .slice()
      .reverse()
      .find((m) => m.type === "user");
    if (!lastUserMsg) {
      setPopup({
        message: "No previously-submitted user message found.",
        type: "error",
      });
      return;
    }

    // We call onSubmit, passing a `messageOverride`
    onSubmit({
      messageIdToResend: lastUserMsg.messageId,
      messageOverride: lastUserMsg.message,
    });
  };

  // UI FUNCTION: Show chat sharing modal for specific chat session
  const openShareModal = (chatSession: ChatSession) => {
    setSharedChatSession(chatSession);
  };
  // UI STATE: Assistants modal visibility (for managing and selecting assistants)
  const [isAssistantsModalOpen, setIsAssistantsModalOpen] = useState(false);

  interface RegenerationRequest {
    messageId: number;
    parentMessage: Message;
    forceSearch?: boolean;
  }

  function createRegenerator(regenerationRequest: RegenerationRequest) {
    // Returns new function that only needs `modelOverRide` to be specified when called
    return async function (modelOverride: LlmDescriptor) {
      return await onSubmit({
        modelOverride,
        messageIdToResend: regenerationRequest.parentMessage.messageId,
        regenerationRequest,
        forceSearch: regenerationRequest.forceSearch,
      });
    };
  }
  if (!user) {
    redirect("/auth/login");
  }

  if (noAssistants)
    return (
      <>
        <HealthCheckBanner />
        <NoAssistantModal isAdmin={isAdmin} />
      </>
    );

  // UI EFFECT: Initial session fetch and setup
  useInitialSessionFetch({
    existingChatSessionId,
    defaultAssistantId,
    searchParams,
    chatSessionIdRef,
    loadedIdSessionRef,
    textAreaRef,
    isInitialLoad,
    submitOnLoadPerformed,
    setIsFetchingChatMessages,
    setSelectedAssistantFromId,
    setSelectedAssistant,
    updateCompleteMessageDetail,
    setChatSessionSharedStatus,
    setSelectedMessageForDocDisplay,
    setHasPerformedInitialScroll,
    hasPerformedInitialScroll,
    messageHistory,
    getCurrentChatAnswering,
    clientScrollToBottom,
    onSubmit,
    nameChatSession: async (sessionId: string) => {
      await nameChatSession(sessionId);
    },
    refreshChatSessions,
    filterManager,
    setCurrentMessageFiles,
    clearSelectedDocuments,
    availableAssistants,
  });

  const stopGenerating = useCallback(() => {
    const currentSession = getCurrentSessionId();
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
  }, [
    getCurrentSessionId,
    messageHistory,
    completeMessageDetail,
    updateCompleteMessageDetail,
    updateChatState,
    abortControllers,
    setAbortControllers,
    currentMessageMap,
  ]);

  // Initialize API Key modal on mount if needed
  useEffect(() => {
    if (!shouldShowWelcomeModal) {
      modalActions.openApiKeyModal({
        hide: () => modalActions.closeModal(),
        setPopup: setPopup,
      });
    }
  }, [shouldShowWelcomeModal, modalActions, setPopup]);

  return (
    <>
      <HealthCheckBanner />

      {/* {isApiKeyModalOpen && !shouldShowWelcomeModal && (
        <ApiKeyModal
          hide={() => setIsApiKeyModalOpen(false)}
          setPopup={setPopup}
        />
      )} */}

      {shouldShowWelcomeModal && <WelcomeModal user={user} />}

      {/* Centralized Modal Renderer */}
      <ModalRenderer state={modalState} onClose={modalActions.closeModal} />

      {/* ChatPopup is a custom popup that displays a admin-specified message on initial user visit. 
      Only used in the EE version of the app. */}
      {popup}

      <ChatPopup />

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

      {(isSettingsModalOpen || isUserSettingsModalOpen) && (
        <UserSettingsModal
          setPopup={setPopup}
          setCurrentLlm={(newLlm) => llmManager.updateCurrentLlm(newLlm)}
          defaultModel={user?.preferences.default_model!}
          llmProviders={llmProviders}
          onClose={() => {
            setIsUserSettingsModalOpen(false);
            setIsSettingsModalOpen(false);
          }}
        />
      )}

      {isDocSelectionModalOpen && (
        <FilePickerModal
          setPresentingDocument={setPresentingDocument}
          buttonContent="Set as Context"
          isOpen={true}
          onClose={() => setIsDocSelectionModalOpen(false)}
          onSave={() => {
            setIsDocSelectionModalOpen(false);
          }}
        />
      )}

      <ChatSearchModal
        open={isChatSearchModalOpen}
        onCloseModal={() => setIsChatSearchModalOpen(false)}
      />

      {retrievalEnabled && documentSidebarVisible && settings?.isMobile && (
        <div className="md:hidden">
          <Modal
            hideDividerForTitle
            onOutsideClick={() => setDocumentSidebarVisible(false)}
            title="Sources"
          >
            <DocumentResults
              agenticMessage={
                aiMessage?.sub_questions?.length! > 0 ||
                messageHistory.find(
                  (m) => m.messageId === aiMessage?.parentMessageId
                )?.sub_questions?.length! > 0
                  ? true
                  : false
              }
              humanMessage={humanMessage ?? null}
              setPresentingDocument={setPresentingDocument}
              modal={true}
              ref={innerSidebarElementRef}
              closeSidebar={() => {
                setDocumentSidebarVisible(false);
              }}
              selectedMessage={aiMessage ?? null}
              selectedDocuments={selectedDocuments}
              toggleDocumentSelection={toggleDocumentSelection}
              clearSelectedDocuments={clearSelectedDocuments}
              selectedDocumentTokens={selectedDocumentTokens}
              maxTokens={maxTokens}
              initialWidth={400}
              isOpen={true}
              removeHeader
            />
          </Modal>
        </div>
      )}

      {presentingDocument && (
        <TextView
          presentingDocument={presentingDocument}
          onClose={() => setPresentingDocument(null)}
        />
      )}

      {stackTraceModalContent && (
        <ExceptionTraceModal
          onOutsideClick={() => setStackTraceModalContent(null)}
          exceptionTrace={stackTraceModalContent}
        />
      )}

      {sharedChatSession && (
        <ShareChatSessionModal
          assistantId={liveAssistant?.id}
          message={message}
          modelOverride={llmManager.currentLlm}
          chatSessionId={sharedChatSession.id}
          existingSharedStatus={sharedChatSession.shared_status}
          onClose={() => setSharedChatSession(null)}
          onShare={(shared) =>
            setChatSessionSharedStatus(
              shared
                ? ChatSessionSharedStatus.Public
                : ChatSessionSharedStatus.Private
            )
          }
        />
      )}

      {isSharingModalOpen && chatSessionIdRef.current !== null && (
        <ShareChatSessionModal
          message={message}
          assistantId={liveAssistant?.id}
          modelOverride={llmManager.currentLlm}
          chatSessionId={chatSessionIdRef.current}
          existingSharedStatus={chatSessionSharedStatus}
          onClose={() => setIsSharingModalOpen(false)}
        />
      )}

      {isAssistantsModalOpen && (
        <AssistantModal hideModal={() => setIsAssistantsModalOpen(false)} />
      )}

      <div className="fixed inset-0 flex flex-col text-text-dark">
        <div className="h-[100dvh] overflow-y-hidden">
          <div className="w-full">
            <div
              ref={sidebarElementRef}
              className={`
                flex-none
                fixed
                left-0
                z-40
                bg-neutral-200
                h-screen
                transition-all
                bg-opacity-80
                duration-300
                ease-in-out
                ${
                  !untoggled && (showHistorySidebar || sidebarVisible)
                    ? "opacity-100 w-[250px] translate-x-0"
                    : "opacity-0 w-[250px] pointer-events-none -translate-x-10"
                }`}
            >
              <div className="w-full relative">
                <HistorySidebar
                  toggleChatSessionSearchModal={() =>
                    setIsChatSearchModalOpen((open) => !open)
                  }
                  liveAssistant={liveAssistant}
                  setShowAssistantsModal={setIsAssistantsModalOpen}
                  explicitlyUntoggle={explicitlyUntoggle}
                  reset={reset}
                  page="chat"
                  ref={innerSidebarElementRef}
                  toggleSidebar={toggleSidebar}
                  toggled={sidebarVisible}
                  existingChats={chatSessions}
                  currentChatSession={selectedChatSession}
                  folders={folders}
                  removeToggle={removeToggle}
                  showShareModal={openShareModal} // TODO: ideally we want consistent open/close naming across codebase, out of scope for now
                />
              </div>

              <div
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
                  documentSidebarVisible &&
                  !settings?.isMobile &&
                  "opacity-100 w-[350px]"
                }`}
              ></div>
            </div>
          </div>

          <div
            style={{ transition: "width 0.30s ease-out" }}
            className={`
                flex-none 
                fixed
                right-0
                z-[1000]
                h-screen
                transition-all
                duration-300
                ease-in-out
                bg-transparent
                transition-all
                duration-300
                ease-in-out
                h-full
                ${
                  documentSidebarVisible && !settings?.isMobile
                    ? "w-[400px]"
                    : "w-[0px]"
                }
            `}
          >
            <DocumentResults
              humanMessage={humanMessage ?? null}
              agenticMessage={
                aiMessage?.sub_questions?.length! > 0 ||
                messageHistory.find(
                  (m) => m.messageId === aiMessage?.parentMessageId
                )?.sub_questions?.length! > 0
                  ? true
                  : false
              }
              setPresentingDocument={setPresentingDocument}
              modal={false}
              ref={innerSidebarElementRef}
              closeSidebar={() =>
                setTimeout(() => setDocumentSidebarVisible(false), 300)
              }
              selectedMessage={aiMessage ?? null}
              selectedDocuments={selectedDocuments}
              toggleDocumentSelection={toggleDocumentSelection}
              clearSelectedDocuments={clearSelectedDocuments}
              selectedDocumentTokens={selectedDocumentTokens}
              maxTokens={maxTokens}
              initialWidth={400}
              isOpen={documentSidebarVisible && !settings?.isMobile}
            />
          </div>

          <BlurBackground
            visible={!untoggled && (showHistorySidebar || sidebarVisible)}
            onClick={() => toggleSidebar()}
          />

          <div
            ref={masterFlexboxRef}
            className="flex h-full w-full overflow-x-hidden"
          >
            <div
              id="scrollableContainer"
              className="flex h-full relative px-2 flex-col w-full"
            >
              {liveAssistant && (
                <FunctionalHeader
                  // careful when defining callbacks inline as this can cause a rerender of subcomponent on every parent render
                  showUserSettingsModal={() => setIsUserSettingsModalOpen(true)}
                  sidebarToggled={sidebarVisible}
                  reset={() => setMessage("")}
                  page="chat"
                  setSharingModalOpen={
                    chatSessionIdRef.current !== null
                      ? setIsSharingModalOpen
                      : undefined
                  }
                  documentSidebarVisible={
                    documentSidebarVisible && !settings?.isMobile
                  }
                  toggleSidebar={toggleSidebar}
                  currentChatSession={selectedChatSession}
                  hideUserDropdown={user?.is_anonymous_user}
                />
              )}

              {documentSidebarInitialWidth !== undefined && isReady ? (
                <Dropzone
                  key={getCurrentSessionId()}
                  onDrop={(acceptedFiles) =>
                    handleMessageSpecificFileUpload(acceptedFiles)
                  }
                  noClick
                >
                  {({ getRootProps }) => (
                    <div className="flex h-full w-full">
                      {!settings?.isMobile && (
                        <div
                          style={{ transition: "width 0.30s ease-out" }}
                          className={`
                          flex-none 
                          overflow-y-hidden 
                          bg-transparent
                          transition-all 
                          bg-opacity-80
                          duration-300 
                          ease-in-out
                          h-full
                          ${sidebarVisible ? "w-[200px]" : "w-[0px]"}
                      `}
                        ></div>
                      )}

                      <div
                        className={`h-full w-full relative flex-auto transition-margin duration-300 overflow-x-auto mobile:pb-12 desktop:pb-[100px]`}
                        {...getRootProps()}
                      >
                        <div
                          onScroll={handleScroll}
                          className={`w-full h-[calc(100vh-160px)] flex flex-col default-scrollbar overflow-y-auto overflow-x-hidden relative`}
                          ref={scrollableDivRef}
                        >
                          {liveAssistant && (
                            <div className="z-20 fixed top-0 pointer-events-none left-0 w-full flex justify-center overflow-visible">
                              {!settings?.isMobile && (
                                <div
                                  style={{ transition: "width 0.30s ease-out" }}
                                  className={`
                                  flex-none 
                                  overflow-y-hidden 
                                  transition-all 
                                  pointer-events-none
                                  duration-300 
                                  ease-in-out
                                  h-full
                                  ${sidebarVisible ? "w-[200px]" : "w-[0px]"}
                              `}
                                />
                              )}
                            </div>
                          )}
                          {/* ChatBanner is a custom banner that displays a admin-specified message at 
                      the top of the chat page. Oly used in the EE version of the app. */}
                          {messageHistory.length === 0 &&
                            !isFetchingChatMessages &&
                            currentSessionChatState == "input" &&
                            !loadingError &&
                            !submittedMessage && (
                              <div className="h-full  w-[95%] mx-auto flex flex-col justify-center items-center">
                                <ChatIntro selectedPersona={liveAssistant} />

                                {currentPersona && (
                                  <StarterMessages
                                    currentPersona={currentPersona}
                                    onSubmit={(messageOverride) =>
                                      onSubmit({
                                        messageOverride,
                                      })
                                    }
                                  />
                                )}
                              </div>
                            )}
                          <div
                            style={{ overflowAnchor: "none" }}
                            key={getCurrentSessionId()}
                            className={
                              (hasPerformedInitialScroll ? "" : " hidden ") +
                              "desktop:-ml-4 w-full mx-auto " +
                              "absolute mobile:top-0 desktop:top-0 left-0 " +
                              (settings?.enterpriseSettings
                                ?.two_lines_for_chat_header
                                ? "pt-20 "
                                : "pt-4 ")
                            }
                            // NOTE: temporarily removing this to fix the scroll bug
                            // (hasPerformedInitialScroll ? "" : "invisible")
                          >
                            {messageHistory.map((message, i) => {
                              const messageMap = currentMessageMap(
                                completeMessageDetail
                              );

                              if (
                                getCurrentRegenerationState()
                                  ?.finalMessageIndex &&
                                getCurrentRegenerationState()
                                  ?.finalMessageIndex! < message.messageId
                              ) {
                                return <></>;
                              }

                              const messageReactComponentKey = `${i}-${getCurrentSessionId()}`;
                              const parentMessage = message.parentMessageId
                                ? messageMap.get(message.parentMessageId)
                                : null;
                              if (message.type === "user") {
                                if (
                                  (currentSessionChatState == "loading" &&
                                    i == messageHistory.length - 1) ||
                                  (currentSessionRegenerationState?.regenerating &&
                                    message.messageId >=
                                      currentSessionRegenerationState?.finalMessageIndex!)
                                ) {
                                  return <></>;
                                }
                                const nextMessage =
                                  messageHistory.length > i + 1
                                    ? messageHistory[i + 1]
                                    : null;
                                return (
                                  <div
                                    id={`message-${message.messageId}`}
                                    key={messageReactComponentKey}
                                  >
                                    <HumanMessage
                                      setPresentingDocument={
                                        setPresentingDocument
                                      }
                                      disableSwitchingForStreaming={
                                        (nextMessage &&
                                          nextMessage.is_generating) ||
                                        false
                                      }
                                      stopGenerating={stopGenerating}
                                      content={message.message}
                                      files={message.files}
                                      messageId={message.messageId}
                                      onEdit={(editedContent) => {
                                        const parentMessageId =
                                          message.parentMessageId!;
                                        const parentMessage =
                                          messageMap.get(parentMessageId)!;
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
                                      otherMessagesCanSwitchTo={
                                        parentMessage?.childrenMessageIds || []
                                      }
                                      onMessageSelection={(messageId) => {
                                        const newCompleteMessageMap = new Map(
                                          messageMap
                                        );
                                        newCompleteMessageMap.get(
                                          message.parentMessageId!
                                        )!.latestChildMessageId = messageId;
                                        updateCompleteMessageDetail(
                                          getCurrentSessionId(),
                                          newCompleteMessageMap
                                        );
                                        setSelectedMessageForDocDisplay(
                                          messageId
                                        );
                                        // set message as latest so we can edit this message
                                        // and so it sticks around on page reload
                                        setMessageAsLatest(messageId);
                                      }}
                                    />
                                  </div>
                                );
                              } else if (message.type === "assistant") {
                                const previousMessage =
                                  i !== 0 ? messageHistory[i - 1] : null;

                                const currentAlternativeAssistant =
                                  message.alternateAssistantID != null
                                    ? availableAssistants.find(
                                        (persona) =>
                                          persona.id ==
                                          message.alternateAssistantID
                                      )
                                    : null;

                                if (
                                  (currentSessionChatState == "loading" &&
                                    i > messageHistory.length - 1) ||
                                  (currentSessionRegenerationState?.regenerating &&
                                    message.messageId >
                                      currentSessionRegenerationState?.finalMessageIndex!)
                                ) {
                                  return <></>;
                                }
                                if (parentMessage?.type == "assistant") {
                                  return <></>;
                                }
                                const secondLevelMessage =
                                  messageHistory[i + 1]?.type === "assistant"
                                    ? messageHistory[i + 1]
                                    : undefined;

                                const secondLevelAssistantMessage =
                                  messageHistory[i + 1]?.type === "assistant"
                                    ? messageHistory[i + 1]?.message
                                    : undefined;

                                const agenticDocs =
                                  messageHistory[i + 1]?.type === "assistant"
                                    ? messageHistory[i + 1]?.documents
                                    : undefined;

                                const nextMessage =
                                  messageHistory[i + 1]?.type === "assistant"
                                    ? messageHistory[i + 1]
                                    : undefined;

                                const attachedFileDescriptors =
                                  previousMessage?.files.filter(
                                    (file) =>
                                      file.type == ChatFileType.USER_KNOWLEDGE
                                  );
                                const userFiles = allUserFiles?.filter(
                                  (file) =>
                                    attachedFileDescriptors?.some(
                                      (descriptor) =>
                                        descriptor.id === file.file_id
                                    )
                                );

                                return (
                                  <div
                                    className="text-text"
                                    id={`message-${message.messageId}`}
                                    key={messageReactComponentKey}
                                    ref={
                                      i == messageHistory.length - 1
                                        ? lastMessageRef
                                        : null
                                    }
                                  >
                                    {message.is_agentic ? (
                                      <AgenticMessage
                                        resubmit={handleResubmitLastMessage}
                                        error={uncaughtError}
                                        isStreamingQuestions={
                                          message.isStreamingQuestions ?? false
                                        }
                                        isGenerating={
                                          message.is_generating ?? false
                                        }
                                        docSidebarToggled={
                                          documentSidebarVisible &&
                                          (selectedMessageForDocDisplay ==
                                            message.messageId ||
                                            selectedMessageForDocDisplay ==
                                              secondLevelMessage?.messageId)
                                        }
                                        secondLevelGenerating={
                                          (message.second_level_generating &&
                                            currentSessionChatState !==
                                              "input") ||
                                          false
                                        }
                                        secondLevelSubquestions={message.sub_questions?.filter(
                                          (subQuestion) =>
                                            subQuestion.level === 1
                                        )}
                                        secondLevelAssistantMessage={
                                          (message.second_level_message &&
                                          message.second_level_message.length >
                                            0
                                            ? message.second_level_message
                                            : secondLevelAssistantMessage) ||
                                          undefined
                                        }
                                        subQuestions={
                                          message.sub_questions?.filter(
                                            (subQuestion) =>
                                              subQuestion.level === 0
                                          ) || []
                                        }
                                        agenticDocs={
                                          message.agentic_docs || agenticDocs
                                        }
                                        docs={
                                          message?.documents &&
                                          message?.documents.length > 0
                                            ? message?.documents
                                            : parentMessage?.documents
                                        }
                                        setPresentingDocument={
                                          setPresentingDocument
                                        }
                                        continueGenerating={
                                          i == messageHistory.length - 1 &&
                                          getCurrentCanContinue()
                                            ? continueGenerating
                                            : undefined
                                        }
                                        overriddenModel={
                                          message.overridden_model
                                        }
                                        regenerate={createRegenerator({
                                          messageId: message.messageId,
                                          parentMessage: parentMessage!,
                                        })}
                                        otherMessagesCanSwitchTo={
                                          parentMessage?.childrenMessageIds ||
                                          []
                                        }
                                        onMessageSelection={(messageId) => {
                                          const newCompleteMessageMap = new Map(
                                            messageMap
                                          );
                                          newCompleteMessageMap.get(
                                            message.parentMessageId!
                                          )!.latestChildMessageId = messageId;

                                          updateCompleteMessageDetail(
                                            getCurrentSessionId(),
                                            newCompleteMessageMap
                                          );

                                          setSelectedMessageForDocDisplay(
                                            messageId
                                          );
                                          // set message as latest so we can edit this message
                                          // and so it sticks around on page reload
                                          setMessageAsLatest(messageId);
                                        }}
                                        isActive={
                                          messageHistory.length - 1 == i ||
                                          messageHistory.length - 2 == i
                                        }
                                        toggleDocumentSelection={(
                                          second: boolean
                                        ) => {
                                          if (
                                            (!second &&
                                              !documentSidebarVisible) ||
                                            (documentSidebarVisible &&
                                              selectedMessageForDocDisplay ===
                                                message.messageId)
                                          ) {
                                            toggleDocumentSidebar();
                                          }
                                          if (
                                            (second &&
                                              !documentSidebarVisible) ||
                                            (documentSidebarVisible &&
                                              selectedMessageForDocDisplay ===
                                                secondLevelMessage?.messageId)
                                          ) {
                                            toggleDocumentSidebar();
                                          }

                                          setSelectedMessageForDocDisplay(
                                            second
                                              ? secondLevelMessage?.messageId ||
                                                  null
                                              : message.messageId
                                          );
                                        }}
                                        currentPersona={liveAssistant}
                                        alternativeAssistant={
                                          currentAlternativeAssistant
                                        }
                                        messageId={message.messageId}
                                        content={message.message}
                                        files={message.files}
                                        query={
                                          messageHistory[i]?.query || undefined
                                        }
                                        citedDocuments={getCitedDocumentsFromMessage(
                                          message
                                        )}
                                        toolCall={message.toolCall}
                                        isComplete={
                                          i !== messageHistory.length - 1 ||
                                          (currentSessionChatState !=
                                            "streaming" &&
                                            currentSessionChatState !=
                                              "toolBuilding")
                                        }
                                        handleFeedback={
                                          i === messageHistory.length - 1 &&
                                          currentSessionChatState != "input"
                                            ? undefined
                                            : (feedbackType: FeedbackType) =>
                                                setCurrentFeedback([
                                                  feedbackType,
                                                  message.messageId as number,
                                                ])
                                        }
                                      />
                                    ) : (
                                      <AIMessage
                                        userKnowledgeFiles={userFiles}
                                        docs={
                                          message?.documents &&
                                          message?.documents.length > 0
                                            ? message?.documents
                                            : parentMessage?.documents
                                        }
                                        setPresentingDocument={
                                          setPresentingDocument
                                        }
                                        index={i}
                                        continueGenerating={
                                          i == messageHistory.length - 1 &&
                                          getCurrentCanContinue()
                                            ? continueGenerating
                                            : undefined
                                        }
                                        overriddenModel={
                                          message.overridden_model
                                        }
                                        regenerate={createRegenerator({
                                          messageId: message.messageId,
                                          parentMessage: parentMessage!,
                                        })}
                                        otherMessagesCanSwitchTo={
                                          parentMessage?.childrenMessageIds ||
                                          []
                                        }
                                        onMessageSelection={(messageId) => {
                                          const newCompleteMessageMap = new Map(
                                            messageMap
                                          );
                                          newCompleteMessageMap.get(
                                            message.parentMessageId!
                                          )!.latestChildMessageId = messageId;

                                          updateCompleteMessageDetail(
                                            getCurrentSessionId(),
                                            newCompleteMessageMap
                                          );

                                          setSelectedMessageForDocDisplay(
                                            messageId
                                          );
                                          // set message as latest so we can edit this message
                                          // and so it sticks around on page reload
                                          setMessageAsLatest(messageId);
                                        }}
                                        isActive={
                                          messageHistory.length - 1 == i
                                        }
                                        selectedDocuments={selectedDocuments}
                                        toggleDocumentSelection={() => {
                                          if (
                                            !documentSidebarVisible ||
                                            (documentSidebarVisible &&
                                              selectedMessageForDocDisplay ===
                                                message.messageId)
                                          ) {
                                            toggleDocumentSidebar();
                                          }

                                          setSelectedMessageForDocDisplay(
                                            message.messageId
                                          );
                                        }}
                                        currentPersona={liveAssistant}
                                        alternativeAssistant={
                                          currentAlternativeAssistant
                                        }
                                        messageId={message.messageId}
                                        content={message.message}
                                        files={message.files}
                                        query={
                                          messageHistory[i]?.query || undefined
                                        }
                                        citedDocuments={getCitedDocumentsFromMessage(
                                          message
                                        )}
                                        toolCall={message.toolCall}
                                        isComplete={
                                          i !== messageHistory.length - 1 ||
                                          (currentSessionChatState !=
                                            "streaming" &&
                                            currentSessionChatState !=
                                              "toolBuilding")
                                        }
                                        hasDocs={
                                          (message.documents &&
                                            message.documents.length > 0) ===
                                          true
                                        }
                                        handleFeedback={
                                          i === messageHistory.length - 1 &&
                                          currentSessionChatState != "input"
                                            ? undefined
                                            : (feedbackType) =>
                                                setCurrentFeedback([
                                                  feedbackType,
                                                  message.messageId as number,
                                                ])
                                        }
                                        handleSearchQueryEdit={
                                          i === messageHistory.length - 1 &&
                                          currentSessionChatState == "input"
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
                                                  previousMessage.messageId ===
                                                  null
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
                                                  alternativeAssistantOverride:
                                                    currentAlternativeAssistant,
                                                });
                                              }
                                            : undefined
                                        }
                                        handleForceSearch={() => {
                                          if (
                                            previousMessage &&
                                            previousMessage.messageId
                                          ) {
                                            createRegenerator({
                                              messageId: message.messageId,
                                              parentMessage: parentMessage!,
                                              forceSearch: true,
                                            })(llmManager.currentLlm);
                                          } else {
                                            setPopup({
                                              type: "error",
                                              message:
                                                "Failed to force search - please refresh the page and try again.",
                                            });
                                          }
                                        }}
                                        retrievalDisabled={
                                          currentAlternativeAssistant
                                            ? !personaIncludesRetrieval(
                                                currentAlternativeAssistant!
                                              )
                                            : !retrievalEnabled
                                        }
                                      />
                                    )}
                                  </div>
                                );
                              } else {
                                return (
                                  <div key={messageReactComponentKey}>
                                    <AIMessage
                                      setPresentingDocument={
                                        setPresentingDocument
                                      }
                                      currentPersona={liveAssistant}
                                      messageId={message.messageId}
                                      content={
                                        <ErrorBanner
                                          resubmit={handleResubmitLastMessage}
                                          error={message.message}
                                          showStackTrace={
                                            message.stackTrace
                                              ? () =>
                                                  setStackTraceModalContent(
                                                    message.stackTrace!
                                                  )
                                              : undefined
                                          }
                                        />
                                      }
                                    />
                                  </div>
                                );
                              }
                            })}

                            {(currentSessionChatState == "loading" ||
                              (loadingError &&
                                !currentSessionRegenerationState?.regenerating &&
                                messageHistory[messageHistory.length - 1]
                                  ?.type != "user")) && (
                              <HumanMessage
                                setPresentingDocument={setPresentingDocument}
                                key={-2}
                                messageId={-1}
                                content={submittedMessage}
                              />
                            )}

                            {currentSessionChatState == "loading" && (
                              <div
                                key={`${messageHistory.length}-${chatSessionIdRef.current}`}
                              >
                                <AIMessage
                                  setPresentingDocument={setPresentingDocument}
                                  key={-3}
                                  currentPersona={liveAssistant}
                                  alternativeAssistant={
                                    alternativeGeneratingAssistant ??
                                    alternativeAssistant
                                  }
                                  messageId={null}
                                  content={
                                    <div
                                      key={"Generating"}
                                      className="mr-auto relative inline-block"
                                    >
                                      <span className="text-sm loading-text">
                                        Thinking...
                                      </span>
                                    </div>
                                  }
                                />
                              </div>
                            )}

                            {loadingError && (
                              <div key={-1}>
                                <AIMessage
                                  setPresentingDocument={setPresentingDocument}
                                  currentPersona={liveAssistant}
                                  messageId={-1}
                                  content={
                                    <p className="text-red-700 text-sm my-auto">
                                      {loadingError}
                                    </p>
                                  }
                                />
                              </div>
                            )}
                            {messageHistory.length > 0 && (
                              <div
                                style={{
                                  height: !autoScrollEnabled
                                    ? getContainerHeight()
                                    : undefined,
                                }}
                              />
                            )}

                            {/* Some padding at the bottom so the search bar has space at the bottom to not cover the last message*/}
                            <div ref={endPaddingRef} className="h-[95px]" />

                            <div ref={endDivRef} />
                          </div>
                        </div>
                        <div
                          ref={inputRef}
                          className="absolute pointer-events-none bottom-0 z-10 w-full"
                        >
                          {aboveHorizon && (
                            <div className="mx-auto w-fit !pointer-events-none flex sticky justify-center">
                              <button
                                onClick={() => clientScrollToBottom()}
                                className="p-1 pointer-events-auto text-neutral-700 dark:text-neutral-800 rounded-2xl bg-neutral-200 border border-border  mx-auto "
                              >
                                <FiArrowDown size={18} />
                              </button>
                            </div>
                          )}

                          <div className="pointer-events-auto w-[95%] mx-auto relative mb-8">
                            <ChatInputBar
                              proSearchEnabled={proSearchEnabled}
                              setProSearchEnabled={toggleProSearch}
                              toggleDocumentSidebar={toggleDocumentSidebar}
                              availableSources={sources}
                              availableDocumentSets={documentSets}
                              availableTags={tags}
                              filterManager={filterManager}
                              llmManager={llmManager}
                              removeDocs={() => {
                                clearSelectedDocuments();
                              }}
                              retrievalEnabled={retrievalEnabled}
                              showDocSelectionModal={() =>
                                setIsDocSelectionModalOpen(true)
                              }
                              showConfigureAPIKey={() =>
                                modalActions.openApiKeyModal({
                                  hide: () => modalActions.closeModal(),
                                  setPopup: setPopup,
                                })
                              }
                              selectedDocuments={selectedDocuments}
                              message={message}
                              setMessage={setMessage}
                              stopGenerating={stopGenerating}
                              onSubmit={onSubmit}
                              chatState={currentSessionChatState}
                              alternativeAssistant={alternativeAssistant}
                              selectedAssistant={
                                selectedAssistant || liveAssistant
                              }
                              setAlternativeAssistant={setAlternativeAssistant}
                              setFiles={setCurrentMessageFiles}
                              handleFileUpload={handleMessageSpecificFileUpload}
                              textAreaRef={textAreaRef}
                            />
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

                      <div
                        style={{ transition: "width 0.30s ease-out" }}
                        className={`
                          flex-none 
                          overflow-y-hidden 
                          transition-all 
                          bg-opacity-80
                          duration-300 
                          ease-in-out
                          h-full
                          ${
                            documentSidebarVisible && !settings?.isMobile
                              ? "w-[350px]"
                              : "w-[0px]"
                          }
                      `}
                      />
                    </div>
                  )}
                </Dropzone>
              ) : (
                <div className="mx-auto h-full flex">
                  <div
                    style={{ transition: "width 0.30s ease-out" }}
                    className={`flex-none bg-transparent transition-all bg-opacity-80 duration-300 ease-in-out h-full
                        ${
                          sidebarVisible && !settings?.isMobile
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
          <FixedLogo backgroundToggled={sidebarVisible || showHistorySidebar} />
        </div>
      </div>
    </>
  );
}
