"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";
import { useRouter, useSearchParams } from "next/navigation";
import {
  createChatSession,
  personaIncludesRetrieval,
} from "@/app/app/services/lib";
import { SEARCH_PARAM_NAMES } from "@/app/app/services/searchParams";
import { errorHandlingFetcher } from "@/lib/fetcher";
import type { MinimalPersonaSnapshot } from "@/app/admin/agents/interfaces";
import { useAgents } from "@/hooks/useAgents";
import useChatSessions from "@/hooks/useChatSessions";
import useChatController, { OnSubmitProps } from "@/hooks/useChatController";
import useChatSessionController from "@/hooks/useChatSessionController";
import useAgentController from "@/hooks/useAgentController";
import { useLlmManager, useFilters } from "@/lib/hooks";
import { useProjectsContext } from "@/providers/ProjectsContext";
import { useUser } from "@/providers/UserProvider";
import {
  useChatSessionStore,
  useCurrentMessageHistory,
  useCurrentChatState,
  useIsReady,
} from "@/app/app/stores/useChatSessionStore";
import ChatScrollContainer, {
  ChatScrollContainerHandle,
} from "@/sections/chat/ChatScrollContainer";
import ChatUI from "@/sections/chat/ChatUI";
import AppInputBar, { AppInputBarHandle } from "@/sections/input/AppInputBar";
import { MinimalOnyxDocument, OnyxDocument } from "@/lib/search/interfaces";
import TutorChatHeader from "@/refresh-pages/tutor/TutorChatHeader";
import TutorHistoryPanel from "@/refresh-pages/tutor/TutorHistoryPanel";
import TutorSuggestions from "@/refresh-pages/tutor/TutorSuggestions";
import TutorNoAgent from "@/refresh-pages/tutor/TutorNoAgent";
import TutorPickerView from "@/refresh-pages/tutor/TutorPickerView";
import CanvasCourseSetupView, {
  CanvasCoursePreparingView,
  type LtiCourseConnectorStatus,
} from "@/refresh-pages/tutor/CanvasCourseSetupView";
import OnyxInitializingLoader from "@/components/OnyxInitializingLoader";
import { Button } from "@opal/components";
import { SvgChevronDown } from "@opal/icons";
import Dropzone from "react-dropzone";
import { cn } from "@/lib/utils";

function BlankLtiStartupView() {
  return (
    <div
      className="h-screen w-full bg-background-neutral-00"
      aria-hidden="true"
    />
  );
}

export default function TutorChatPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user, isAdmin, isCurator } = useUser();
  const isInstructor = isAdmin || isCurator;

  // URL params from LTI launch
  const assistantIdRaw = searchParams?.get(SEARCH_PARAM_NAMES.PERSONA_ID);
  const assistantId = assistantIdRaw ? parseInt(assistantIdRaw) : null;
  const projectIdRaw = searchParams?.get(SEARCH_PARAM_NAMES.PROJECT_ID);
  const projectId = projectIdRaw ? parseInt(projectIdRaw) : null;
  const ltiContextId =
    searchParams?.get(SEARCH_PARAM_NAMES.LTI_CONTEXT_ID) ?? null;
  const ltiCanvasCourseNodeId =
    searchParams?.get(SEARCH_PARAM_NAMES.LTI_CANVAS_COURSE_NODE_ID) ?? null;

  // State
  const [historyOpen, setHistoryOpen] = useState(false);
  const [selectedDocuments, setSelectedDocuments] = useState<OnyxDocument[]>(
    []
  );

  // Refs
  const chatInputBarRef = useRef<AppInputBarHandle>(null);
  const scrollContainerRef = useRef<ChatScrollContainerHandle>(null);
  const chatSessionIdRef = useRef<string | null>(null);
  const loadedIdSessionRef = useRef<string | null>(null);
  const isInitialLoad = useRef(true);
  const submitOnLoadPerformed = useRef<boolean>(false);

  // Data hooks
  const { agents, isLoading: isLoadingAgents } = useAgents();

  // The set of tutors that belong to the current Canvas course. Used to scope
  // the History panel to only conversations with this course's tutors.
  const courseTutorsSwrKey = ltiContextId
    ? `/api/auth/lti/tutors-for-course?context_id=${encodeURIComponent(
        ltiContextId
      )}`
    : null;
  const { data: courseTutors } = useSWR<MinimalPersonaSnapshot[]>(
    courseTutorsSwrKey,
    errorHandlingFetcher
  );
  const courseConnectorStatusSwrKey = ltiContextId
    ? `/api/auth/lti/course/${encodeURIComponent(
        ltiContextId
      )}/connector-status`
    : null;
  const {
    data: courseConnectorStatus,
    error: courseConnectorStatusError,
    isLoading: isLoadingCourseConnectorStatus,
    mutate: refreshCourseConnectorStatus,
  } = useSWR<LtiCourseConnectorStatus>(
    courseConnectorStatusSwrKey,
    errorHandlingFetcher,
    {
      refreshInterval: (latestStatus) => {
        if (!latestStatus) return 0;
        if (!latestStatus.has_connector) return 5000;
        return latestStatus.has_indexed_documents ? 0 : 5000;
      },
    }
  );
  const courseTutorIds = useMemo(() => {
    if (!courseTutors) return null;
    return new Set(courseTutors.map((t) => t.id));
  }, [courseTutors]);
  const canManageCourseTutors =
    isInstructor || Boolean(courseConnectorStatus?.setup);

  const {
    chatSessions,
    refreshChatSessions,
    currentChatSession,
    currentChatSessionId,
  } = useChatSessions();
  const { currentMessageFiles, setCurrentMessageFiles } = useProjectsContext();

  // Find the tutor agent
  const tutorAgent = useMemo(() => {
    if (!assistantId || agents.length === 0) return null;
    return agents.find((a) => a.id === assistantId) ?? null;
  }, [assistantId, agents]);

  const { selectedAgent, setSelectedAgentFromId, liveAgent } =
    useAgentController({
      selectedChatSession: currentChatSession,
    });

  // Use the tutor agent if we have one, otherwise fall back to the controller's agent
  const effectiveAgent = tutorAgent ?? liveAgent;

  const filterManager = useFilters();
  const llmManager = useLlmManager(
    currentChatSession ?? undefined,
    effectiveAgent
  );

  const resetInputBar = useCallback(() => {
    chatInputBarRef.current?.reset();
    setCurrentMessageFiles([]);
  }, [setCurrentMessageFiles]);

  const {
    onSubmit,
    stopGenerating,
    handleMessageSpecificFileUpload,
    availableContextTokens,
  } = useChatController({
    filterManager,
    llmManager,
    availableAgents: agents,
    liveAgent: effectiveAgent,
    existingChatSessionId: currentChatSessionId,
    selectedDocuments,
    searchParams,
    resetInputBar,
    setSelectedAgentFromId,
  });

  const {
    onMessageSelection,
    currentSessionFileTokenCount,
    sessionFetchError,
  } = useChatSessionController({
    existingChatSessionId: currentChatSessionId,
    searchParams: searchParams!,
    filterManager,
    setSelectedAgentFromId,
    setSelectedDocuments,
    setCurrentMessageFiles,
    chatSessionIdRef,
    loadedIdSessionRef,
    chatInputBarRef,
    isInitialLoad,
    submitOnLoadPerformed,
    refreshChatSessions,
    onSubmit,
  });

  // Chat state from store
  const currentChatState = useCurrentChatState();
  const isReady = useIsReady();
  const messageHistory = useCurrentMessageHistory();
  const [showScrollButton, setShowScrollButton] = useState(false);

  // Auto-scroll
  const autoScrollEnabled = user?.preferences?.auto_scroll !== false;
  const isStreaming = currentChatState === "streaming";

  // Determine anchor for scroll container
  const anchorMessage = messageHistory.at(-2) ?? messageHistory[0];
  const anchorNodeId = anchorMessage?.nodeId;
  const anchorSelector = anchorNodeId ? `#message-${anchorNodeId}` : undefined;

  // Reset scroll button on session change
  useEffect(() => {
    setShowScrollButton(false);
  }, [currentChatSessionId]);

  const handleScrollToBottom = useCallback(() => {
    scrollContainerRef.current?.scrollToBottom();
  }, []);

  const handleCanvasConnectorReady = useCallback(() => {
    void refreshCourseConnectorStatus();
  }, [refreshCourseConnectorStatus]);

  // Derive course name from project (strip "[Canvas] " prefix)
  const courseName = useMemo(() => {
    if (!currentChatSession?.project_id) return null;
    // We don't have the project name readily available from chat sessions,
    // so we'll just show the tutor name.
    return null;
  }, [currentChatSession]);

  // New conversation handler
  const handleNewConversation = useCallback(() => {
    const params = new URLSearchParams();
    if (assistantId)
      params.set(SEARCH_PARAM_NAMES.PERSONA_ID, String(assistantId));
    if (projectId) params.set(SEARCH_PARAM_NAMES.PROJECT_ID, String(projectId));
    if (ltiContextId)
      params.set(SEARCH_PARAM_NAMES.LTI_CONTEXT_ID, ltiContextId);
    if (ltiCanvasCourseNodeId)
      params.set(
        SEARCH_PARAM_NAMES.LTI_CANVAS_COURSE_NODE_ID,
        ltiCanvasCourseNodeId
      );
    router.push(`/tutor?${params.toString()}`);
  }, [router, assistantId, projectId, ltiContextId, ltiCanvasCourseNodeId]);

  // Manage tutors: jump back to the picker for the current course.
  const handleManageTutors = useCallback(() => {
    if (!ltiContextId) return;
    const params = new URLSearchParams();
    params.set(SEARCH_PARAM_NAMES.LTI_CONTEXT_ID, ltiContextId);
    if (projectId) params.set(SEARCH_PARAM_NAMES.PROJECT_ID, String(projectId));
    if (ltiCanvasCourseNodeId)
      params.set(
        SEARCH_PARAM_NAMES.LTI_CANVAS_COURSE_NODE_ID,
        ltiCanvasCourseNodeId
      );
    router.push(`/tutor?${params.toString()}`);
  }, [router, ltiContextId, projectId, ltiCanvasCourseNodeId]);

  // Select a session from history
  const handleSelectSession = useCallback(
    (sessionId: string) => {
      const params = new URLSearchParams();
      params.set(SEARCH_PARAM_NAMES.CHAT_ID, sessionId);
      if (assistantId)
        params.set(SEARCH_PARAM_NAMES.PERSONA_ID, String(assistantId));
      if (projectId)
        params.set(SEARCH_PARAM_NAMES.PROJECT_ID, String(projectId));
      if (ltiContextId)
        params.set(SEARCH_PARAM_NAMES.LTI_CONTEXT_ID, ltiContextId);
      if (ltiCanvasCourseNodeId)
        params.set(
          SEARCH_PARAM_NAMES.LTI_CANVAS_COURSE_NODE_ID,
          ltiCanvasCourseNodeId
        );
      router.push(`/tutor?${params.toString()}`);
      setHistoryOpen(false);
    },
    [router, assistantId, projectId, ltiContextId, ltiCanvasCourseNodeId]
  );

  // Submit message handler
  const handleSubmit = useCallback(
    async (message: string) => {
      resetInputBar();
      onSubmit({
        message,
        currentMessageFiles,
        deepResearch: false,
      });
    },
    [resetInputBar, onSubmit, currentMessageFiles]
  );

  // Resubmit last message
  const handleResubmit = useCallback(() => {
    const lastUserMsg = messageHistory
      .slice()
      .reverse()
      .find((m) => m.type === "user");
    if (!lastUserMsg) return;
    onSubmit({
      message: lastUserMsg.message,
      currentMessageFiles,
      deepResearch: false,
      messageIdToResend: lastUserMsg.messageId,
    });
  }, [messageHistory, onSubmit, currentMessageFiles]);

  // Toggle history panel
  const toggleHistory = useCallback(() => {
    setHistoryOpen((prev) => !prev);
  }, []);

  // Loading state
  if (!isReady) {
    if (ltiContextId) return <BlankLtiStartupView />;
    return <OnyxInitializingLoader />;
  }

  if (ltiContextId && isLoadingCourseConnectorStatus) {
    return <BlankLtiStartupView />;
  }

  if (ltiContextId && courseConnectorStatusError) {
    return <TutorNoAgent />;
  }

  if (ltiContextId && courseConnectorStatus) {
    if (
      !courseConnectorStatus.has_connector &&
      courseConnectorStatus.setup?.can_setup
    ) {
      return (
        <CanvasCourseSetupView
          courseId={ltiContextId}
          status={courseConnectorStatus}
          onReady={handleCanvasConnectorReady}
        />
      );
    }

    if (
      !courseConnectorStatus.has_connector ||
      !courseConnectorStatus.has_indexed_documents
    ) {
      return <CanvasCoursePreparingView status={courseConnectorStatus} />;
    }
  }

  // No agentId chosen yet — render the picker if we know the course context,
  // otherwise fall back to the legacy no-agent state.
  if (!assistantId) {
    if (ltiContextId) {
      return (
        <TutorPickerView
          ltiContextId={ltiContextId}
          projectId={projectId}
          ltiCanvasCourseNodeId={ltiCanvasCourseNodeId}
          canManageTutors={canManageCourseTutors}
        />
      );
    }
    if (!isLoadingAgents) {
      return <TutorNoAgent />;
    }
  }

  // We have an agentId but the agent itself failed to resolve.
  if (!effectiveAgent && !isLoadingAgents) {
    return <TutorNoAgent />;
  }

  const hasMessages = currentChatSessionId && messageHistory.length > 0;
  const hasStarterMessages =
    (effectiveAgent?.starter_messages?.length ?? 0) > 0;

  return (
    <div className="flex h-full w-full">
      {/* History panel (collapsible) */}
      {historyOpen && (
        <TutorHistoryPanel
          sessions={chatSessions}
          currentSessionId={currentChatSessionId}
          allowedPersonaIds={courseTutorIds}
          onSelectSession={handleSelectSession}
          onClose={() => setHistoryOpen(false)}
        />
      )}

      {/* Main chat area */}
      <div className="flex flex-col flex-1 min-w-0">
        <TutorChatHeader
          agent={effectiveAgent ?? null}
          courseName={courseName}
          onNewConversation={handleNewConversation}
          onToggleHistory={toggleHistory}
          historyOpen={historyOpen}
          onManageTutors={
            canManageCourseTutors && ltiContextId ? handleManageTutors : null
          }
        />

        <Dropzone
          onDrop={(files) => handleMessageSpecificFileUpload(files)}
          noClick
        >
          {({ getRootProps }) => (
            <div
              className="flex-1 flex flex-col items-center min-h-0 outline-none"
              {...getRootProps({ tabIndex: -1 })}
            >
              {/* Chat messages or suggestions */}
              <div className="flex-1 w-full min-h-0 flex flex-col items-center">
                {hasMessages && effectiveAgent ? (
                  <ChatScrollContainer
                    ref={scrollContainerRef}
                    sessionId={currentChatSessionId!}
                    anchorSelector={anchorSelector}
                    autoScroll={autoScrollEnabled}
                    isStreaming={isStreaming}
                    onScrollButtonVisibilityChange={setShowScrollButton}
                  >
                    <ChatUI
                      liveAgent={effectiveAgent}
                      llmManager={llmManager}
                      deepResearchEnabled={false}
                      currentMessageFiles={currentMessageFiles}
                      setPresentingDocument={() => {}}
                      onSubmit={onSubmit}
                      onMessageSelection={onMessageSelection}
                      stopGenerating={stopGenerating}
                      onResubmit={handleResubmit}
                      anchorNodeId={anchorNodeId}
                    />
                  </ChatScrollContainer>
                ) : (
                  <div className="flex-1 flex flex-col items-center justify-end w-full max-w-[720px] mx-auto pb-4">
                    {hasStarterMessages && effectiveAgent && (
                      <TutorSuggestions
                        agent={effectiveAgent}
                        onSubmit={onSubmit}
                      />
                    )}
                  </div>
                )}
              </div>

              {/* Input bar */}
              <div className="w-full flex flex-col items-center px-4 pb-3">
                <div className="relative w-full max-w-[720px]">
                  {/* Scroll to bottom button */}
                  {hasMessages && showScrollButton && (
                    <div className="absolute top-[-3.5rem] self-center left-1/2 -translate-x-1/2">
                      <Button
                        icon={SvgChevronDown}
                        onClick={handleScrollToBottom}
                        aria-label="Scroll to bottom"
                        prominence="secondary"
                      />
                    </div>
                  )}
                  <AppInputBar
                    ref={chatInputBarRef}
                    deepResearchEnabled={false}
                    toggleDeepResearch={() => {}}
                    filterManager={filterManager}
                    llmManager={llmManager}
                    stopGenerating={stopGenerating}
                    onSubmit={handleSubmit}
                    chatState={currentChatState}
                    currentSessionFileTokenCount={currentSessionFileTokenCount}
                    availableContextTokens={availableContextTokens}
                    selectedAgent={effectiveAgent}
                    handleFileUpload={handleMessageSpecificFileUpload}
                    setPresentingDocument={() => {}}
                    disabled={
                      !llmManager.isLoadingProviders &&
                      llmManager.hasAnyProvider === false
                    }
                  />
                </div>
              </div>
            </div>
          )}
        </Dropzone>
      </div>
    </div>
  );
}
