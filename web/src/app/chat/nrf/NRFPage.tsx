"use client";
import React, { useState, useEffect, useRef, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import { useUser } from "@/components/user/UserProvider";
import { usePopup } from "@/components/admin/connectors/Popup";
import { AuthType } from "@/lib/constants";
import Button from "@/refresh-components/buttons/Button";
import ChatInputBar, {
  ChatInputBarHandle,
} from "@/app/chat/components/input/ChatInputBar";
import IconButton from "@/refresh-components/buttons/IconButton";
import Modal from "@/refresh-components/Modal";
import { useFilters, useLlmManager } from "@/lib/hooks";
import Dropzone from "react-dropzone";
import { useSendMessageToParent } from "@/lib/extension/utils";
import { useNRFPreferences } from "@/components/context/NRFPreferencesContext";
import { SettingsPanel } from "@/app/components/nrf/SettingsPanel";
import LoginPage from "@/app/auth/login/LoginPage";
import { sendSetDefaultNewTabMessage } from "@/lib/extension/utils";
import { useAgents } from "@/hooks/useAgents";
import { useProjectsContext } from "@/app/chat/projects/ProjectsContext";
import { useDeepResearchToggle } from "@/app/chat/hooks/useDeepResearchToggle";
import { useChatController } from "@/app/chat/hooks/useChatController";
import { useChatSessionController } from "@/app/chat/hooks/useChatSessionController";
import { useAssistantController } from "@/app/chat/hooks/useAssistantController";
import {
  useCurrentChatState,
  useCurrentMessageHistory,
} from "@/app/chat/stores/useChatSessionStore";
import MessageList from "@/components/chat/MessageList";
import ChatScrollContainer from "@/components/chat/ChatScrollContainer";
import WelcomeMessage from "@/app/chat/components/WelcomeMessage";
import useChatSessions from "@/hooks/useChatSessions";
import * as AppLayouts from "@/layouts/app-layouts";
import { cn } from "@/lib/utils";
import Logo from "@/refresh-components/Logo";
import Spacer from "@/refresh-components/Spacer";
import { useAppSidebarContext } from "@/refresh-components/contexts/AppSidebarContext";
import { DEFAULT_CONTEXT_TOKENS } from "@/lib/constants";
import {
  SvgUser,
  SvgMenu,
  SvgExternalLink,
  SvgAlertTriangle,
} from "@opal/icons";
import {
  CHAT_BACKGROUND_NONE,
  getBackgroundById,
} from "@/lib/constants/chatBackgrounds";

interface NRFPageProps {
  isSidePanel?: boolean;
}

// Reserve half of the context window for the model's response output
const AVAILABLE_CONTEXT_TOKENS = Number(DEFAULT_CONTEXT_TOKENS) * 0.5;

export default function NRFPage({ isSidePanel = false }: NRFPageProps) {
  const { setUseOnyxAsNewTab } = useNRFPreferences();

  const searchParams = useSearchParams();
  const filterManager = useFilters();
  const { user, authTypeMetadata } = useUser();
  const { setFolded } = useAppSidebarContext();

  const { popup, setPopup } = usePopup();

  // Hide sidebar when in side panel mode
  useEffect(() => {
    if (isSidePanel) {
      setFolded(true);
    }
  }, [isSidePanel, setFolded]);

  // Chat sessions
  const { refreshChatSessions } = useChatSessions();
  const existingChatSessionId = null; // NRF always starts new chats

  // Get agents for assistant selection
  const { agents: availableAssistants } = useAgents();

  // Projects context for file handling
  const {
    currentMessageFiles,
    setCurrentMessageFiles,
    lastFailedFiles,
    clearLastFailedFiles,
  } = useProjectsContext();

  // Show popup if any files failed
  useEffect(() => {
    if (lastFailedFiles && lastFailedFiles.length > 0) {
      const names = lastFailedFiles.map((f) => f.name).join(", ");
      setPopup({
        type: "error",
        message:
          lastFailedFiles.length === 1
            ? `File failed and was removed: ${names}`
            : `Files failed and were removed: ${names}`,
      });
      clearLastFailedFiles();
    }
  }, [lastFailedFiles, setPopup, clearLastFailedFiles]);

  // Assistant controller
  const { selectedAssistant, setSelectedAssistantFromId, liveAssistant } =
    useAssistantController({
      selectedChatSession: undefined,
      onAssistantSelect: () => {},
    });

  // LLM manager for model selection.
  // - currentChatSession: undefined because NRF always starts new chats
  // - liveAssistant: uses the selected assistant, or undefined to fall back
  //   to system-wide default LLM provider.
  //
  // If no LLM provider is configured (e.g., fresh signup), the input bar is
  // disabled and a "Set up an LLM" button is shown (see bottom of component).
  const llmManager = useLlmManager(undefined, liveAssistant ?? undefined);

  // Deep research toggle
  const { deepResearchEnabled, toggleDeepResearch } = useDeepResearchToggle({
    chatSessionId: existingChatSessionId,
    assistantId: selectedAssistant?.id,
  });

  // State
  const [message, setMessage] = useState("");
  const [settingsOpen, setSettingsOpen] = useState<boolean>(false);

  // Initialize message from URL input parameter (for Chrome extension)
  const initializedRef = useRef(false);
  useEffect(() => {
    if (initializedRef.current) return;
    initializedRef.current = true;
    const urlParams = new URLSearchParams(window.location.search);
    const userPrompt = urlParams.get("user-prompt");
    if (userPrompt) {
      setMessage(userPrompt);
    }
  }, []);

  // Chat background - shared with ChatPage
  const chatBackgroundId = user?.preferences?.chat_background;
  const chatBackground = getBackgroundById(chatBackgroundId ?? null);
  const hasBackground =
    chatBackground && chatBackground.url !== CHAT_BACKGROUND_NONE;

  // Modals
  const [showTurnOffModal, setShowTurnOffModal] = useState<boolean>(false);

  // Refs
  const inputRef = useRef<HTMLDivElement>(null);
  const chatInputBarRef = useRef<ChatInputBarHandle | null>(null);
  const submitOnLoadPerformed = useRef<boolean>(false);

  // Access chat state from store
  const currentChatState = useCurrentChatState();
  const messageHistory = useCurrentMessageHistory();

  // Determine if we should show centered welcome or messages
  const hasMessages = messageHistory.length > 0;

  // Resolved assistant to use throughout the component
  const resolvedAssistant = liveAssistant ?? undefined;

  // Auto-scroll preference from user settings (matches ChatPage pattern)
  const autoScrollEnabled = user?.preferences?.auto_scroll !== false;
  const isStreaming = currentChatState === "streaming";

  // Anchor for scroll positioning (matches ChatPage pattern)
  const anchorMessage = messageHistory.at(-2) ?? messageHistory[0];
  const anchorNodeId = anchorMessage?.nodeId;
  const anchorSelector = anchorNodeId ? `#message-${anchorNodeId}` : undefined;

  useSendMessageToParent();

  const toggleSettings = () => {
    setSettingsOpen((prev) => !prev);
  };

  // If user toggles the "Use Onyx" switch to off, prompt a modal
  const handleUseOnyxToggle = (checked: boolean) => {
    if (!checked) {
      setShowTurnOffModal(true);
    } else {
      setUseOnyxAsNewTab(true);
      sendSetDefaultNewTabMessage(true);
    }
  };

  const confirmTurnOff = () => {
    setUseOnyxAsNewTab(false);
    setShowTurnOffModal(false);
    sendSetDefaultNewTabMessage(false);
  };

  // Reset input bar after sending
  const resetInputBar = useCallback(() => {
    setMessage("");
    setCurrentMessageFiles([]);
    chatInputBarRef.current?.reset();
  }, [setMessage, setCurrentMessageFiles]);

  // Chat controller for submitting messages
  const { onSubmit, stopGenerating, handleMessageSpecificFileUpload } =
    useChatController({
      filterManager,
      llmManager,
      availableAssistants: availableAssistants || [],
      liveAssistant,
      existingChatSessionId,
      selectedDocuments: [],
      searchParams: searchParams!,
      setPopup,
      resetInputBar,
      setSelectedAssistantFromId,
    });

  // Chat session controller for loading sessions
  const { currentSessionFileTokenCount } = useChatSessionController({
    existingChatSessionId,
    searchParams: searchParams!,
    filterManager,
    firstMessage: undefined,
    setSelectedAssistantFromId,
    setSelectedDocuments: () => {}, // No-op: NRF doesn't support document selection
    setCurrentMessageFiles,
    chatSessionIdRef: { current: null },
    loadedIdSessionRef: { current: null },
    chatInputBarRef,
    isInitialLoad: { current: false },
    submitOnLoadPerformed,
    refreshChatSessions,
    onSubmit,
  });

  // Handle file upload
  const handleFileUpload = useCallback(
    async (acceptedFiles: File[]) => {
      handleMessageSpecificFileUpload(acceptedFiles);
    },
    [handleMessageSpecificFileUpload]
  );

  // Handle submit from ChatInputBar
  const handleChatInputSubmit = useCallback(
    (submittedMessage: string) => {
      if (!submittedMessage.trim()) return;
      onSubmit({
        message: submittedMessage,
        currentMessageFiles: currentMessageFiles,
        deepResearch: deepResearchEnabled,
      });
    },
    [onSubmit, currentMessageFiles, deepResearchEnabled]
  );

  // Handle resubmit last message on error
  const handleResubmitLastMessage = useCallback(() => {
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

    onSubmit({
      message: lastUserMsg.message,
      currentMessageFiles: currentMessageFiles,
      deepResearch: deepResearchEnabled,
      messageIdToResend: lastUserMsg.messageId,
    });
  }, [
    messageHistory,
    onSubmit,
    currentMessageFiles,
    deepResearchEnabled,
    setPopup,
  ]);

  const handleOpenInOnyx = () => {
    window.open(`${window.location.origin}/chat`, "_blank");
  };

  return (
    <div
      className={cn(
        "relative w-full h-full flex flex-col overflow-hidden",
        isSidePanel
          ? "bg-background"
          : hasBackground && "bg-cover bg-center bg-fixed"
      )}
      style={
        !isSidePanel && hasBackground
          ? { backgroundImage: `url(${chatBackground.url})` }
          : undefined
      }
    >
      {popup}

      {/* Semi-transparent overlay for readability when background is set */}
      {!isSidePanel && hasBackground && (
        <div className="absolute inset-0 bg-background/80 pointer-events-none" />
      )}

      {/* Side panel header */}
      {isSidePanel && (
        <header className="flex items-center justify-between px-4 py-3 border-b border-border-01 bg-background">
          <div className="flex items-center gap-2">
            <Logo />
          </div>
          <Button
            tertiary
            rightIcon={SvgExternalLink}
            onClick={handleOpenInOnyx}
          >
            Open in Onyx
          </Button>
        </header>
      )}

      {/* Settings button */}
      {!isSidePanel && (
        <div className="absolute top-0 right-0 p-4 z-10">
          <IconButton
            icon={SvgMenu}
            onClick={toggleSettings}
            tertiary
            tooltip="Open settings"
            className="bg-mask-02 backdrop-blur-[12px] rounded-full shadow-01 hover:bg-mask-03"
          />
        </div>
      )}

      <Dropzone onDrop={handleFileUpload} noClick>
        {({ getRootProps }) => (
          <div
            {...getRootProps()}
            className="h-full w-full flex flex-col items-center outline-none"
          >
            {/* Chat area with messages */}
            {hasMessages && resolvedAssistant && (
              <>
                {/* Fake header */}
                <Spacer rem={2} />
                <ChatScrollContainer
                  sessionId="nrf-session"
                  anchorSelector={anchorSelector}
                  autoScroll={autoScrollEnabled}
                  isStreaming={isStreaming}
                  disableFadeOverlay={!isSidePanel}
                >
                  <MessageList
                    liveAssistant={resolvedAssistant}
                    llmManager={llmManager}
                    currentMessageFiles={currentMessageFiles}
                    setPresentingDocument={() => {}}
                    onSubmit={onSubmit}
                    onMessageSelection={() => {}}
                    stopGenerating={stopGenerating}
                    onResubmit={handleResubmitLastMessage}
                    deepResearchEnabled={deepResearchEnabled}
                    anchorNodeId={anchorNodeId}
                    disableBlur={!hasBackground}
                  />
                </ChatScrollContainer>
              </>
            )}

            {/* Welcome message - centered when no messages */}
            {!hasMessages && (
              <div className="w-full flex-1 flex flex-col items-center justify-end">
                <WelcomeMessage isDefaultAgent />
                <Spacer rem={1.5} />
              </div>
            )}

            {/* ChatInputBar container - absolutely positioned when in chat, centered when no messages */}
            <div
              ref={inputRef}
              className={cn(
                "flex justify-center",
                hasMessages
                  ? "absolute bottom-6 left-0 right-0 pointer-events-none"
                  : "w-full"
              )}
            >
              <div
                className={cn(
                  "w-[min(50rem,100%)] flex flex-col px-4",
                  hasMessages && "pointer-events-auto"
                )}
              >
                <ChatInputBar
                  ref={chatInputBarRef}
                  deepResearchEnabled={deepResearchEnabled}
                  toggleDeepResearch={toggleDeepResearch}
                  toggleDocumentSidebar={() => {}}
                  filterManager={filterManager}
                  llmManager={llmManager}
                  removeDocs={() => {}}
                  retrievalEnabled={false}
                  selectedDocuments={[]}
                  initialMessage={message}
                  stopGenerating={stopGenerating}
                  onSubmit={handleChatInputSubmit}
                  chatState={currentChatState}
                  currentSessionFileTokenCount={currentSessionFileTokenCount}
                  availableContextTokens={AVAILABLE_CONTEXT_TOKENS}
                  selectedAssistant={liveAssistant ?? undefined}
                  handleFileUpload={handleFileUpload}
                  disabled={
                    !llmManager.isLoadingProviders && !llmManager.hasAnyProvider
                  }
                />
                <Spacer rem={0.5} />
              </div>
            </div>
            {!hasMessages && <div className="flex-1 w-full" />}
            <AppLayouts.Footer />
          </div>
        )}
      </Dropzone>

      {/* Modals - only show when not in side panel mode */}
      {!isSidePanel && (
        <>
          <SettingsPanel
            settingsOpen={settingsOpen}
            toggleSettings={toggleSettings}
            handleUseOnyxToggle={handleUseOnyxToggle}
          />

          <Modal open={showTurnOffModal} onOpenChange={setShowTurnOffModal}>
            <Modal.Content width="sm">
              <Modal.Header
                icon={SvgAlertTriangle}
                title="Turn off Onyx new tab page?"
                description="You'll see your browser's default new tab page instead. You can turn it back on anytime in your Onyx settings."
                onClose={() => setShowTurnOffModal(false)}
              />
              <Modal.Footer>
                <Button secondary onClick={() => setShowTurnOffModal(false)}>
                  Cancel
                </Button>
                <Button danger onClick={confirmTurnOff}>
                  Turn off
                </Button>
              </Modal.Footer>
            </Modal.Content>
          </Modal>
        </>
      )}

      {!user && authTypeMetadata.authType !== AuthType.DISABLED && (
        <Modal open onOpenChange={() => {}}>
          <Modal.Content width="sm" height="sm">
            <Modal.Header icon={SvgUser} title="Welcome to Onyx" />
            <Modal.Body>
              {authTypeMetadata.authType === AuthType.BASIC ? (
                <LoginPage
                  authUrl={null}
                  authTypeMetadata={authTypeMetadata}
                  nextUrl="/nrf"
                />
              ) : (
                <div className="flex flex-col items-center">
                  <Button
                    className="w-full"
                    secondary
                    onClick={() => {
                      if (window.top) {
                        window.top.location.href = "/auth/login";
                      } else {
                        window.location.href = "/auth/login";
                      }
                    }}
                  >
                    Log in
                  </Button>
                </div>
              )}
            </Modal.Body>
          </Modal.Content>
        </Modal>
      )}

      {user && !llmManager.isLoadingProviders && !llmManager.hasAnyProvider && (
        <Button
          className="w-full"
          secondary
          onClick={() => {
            window.location.href = "/admin/configuration/llm";
          }}
        >
          Set up an LLM.
        </Button>
      )}
    </div>
  );
}
