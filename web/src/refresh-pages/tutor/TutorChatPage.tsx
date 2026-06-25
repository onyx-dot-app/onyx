"use client";

import {
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import useSWR from "swr";
import { useRouter, useSearchParams } from "next/navigation";
import { SEARCH_PARAM_NAMES } from "@/app/app/services/searchParams";
import type { ChatSession } from "@/app/app/interfaces";
import { errorHandlingFetcher } from "@/lib/fetcher";
import type { MinimalPersonaSnapshot } from "@/app/admin/agents/interfaces";
import { useAgents } from "@/hooks/useAgents";
import useChatSessions, {
  type UseChatSessionsOptions,
} from "@/hooks/useChatSessions";
import useChatController from "@/hooks/useChatController";
import useChatSessionController from "@/hooks/useChatSessionController";
import useAgentController from "@/hooks/useAgentController";
import { useLlmManager, useFilters } from "@/lib/hooks";
import { useProjectsContext } from "@/providers/ProjectsContext";
import { useUser } from "@/providers/UserProvider";
import {
  useCurrentMessageHistory,
  useCurrentChatState,
  useIsReady,
} from "@/app/app/stores/useChatSessionStore";
import ChatScrollContainer, {
  ChatScrollContainerHandle,
} from "@/sections/chat/ChatScrollContainer";
import ChatUI from "@/sections/chat/ChatUI";
import AppInputBar, { AppInputBarHandle } from "@/sections/input/AppInputBar";
import { OnyxDocument } from "@/lib/search/interfaces";
import TutorChatHeader from "@/refresh-pages/tutor/TutorChatHeader";
import TutorHistoryPanel from "@/refresh-pages/tutor/TutorHistoryPanel";
import TutorSuggestions from "@/refresh-pages/tutor/TutorSuggestions";
import TutorNoAgent from "@/refresh-pages/tutor/TutorNoAgent";
import TutorPickerView from "@/refresh-pages/tutor/TutorPickerView";
import CanvasCourseSetupView, {
  CanvasCoursePreparingView,
  type LtiCourseConnectorStatus,
} from "@/refresh-pages/tutor/CanvasCourseSetupView";
import TutorInstructorInsights from "@/refresh-pages/tutor/TutorInstructorInsights";
import TutorInstructorKnowledge from "@/refresh-pages/tutor/TutorInstructorKnowledge";
import OnyxInitializingLoader from "@/components/OnyxInitializingLoader";
import { Button, SidebarTab } from "@opal/components";
import {
  SvgBarChart,
  SvgBookOpen,
  SvgChevronDown,
  SvgHistory,
  SvgPlus,
  SvgUsers,
} from "@opal/icons";
import Dropzone from "react-dropzone";
import { useEmbeddedMode } from "@/hooks/useEmbeddedMode";
import { UserRole } from "@/lib/types";

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
  const { user, isAdmin } = useUser();
  const isInstructor = isAdmin || user?.role === UserRole.CURATOR;
  const isEmbedded = useEmbeddedMode();

  // URL params from LTI launch
  const assistantIdRaw = searchParams?.get(SEARCH_PARAM_NAMES.PERSONA_ID);
  const assistantId = assistantIdRaw ? parseInt(assistantIdRaw) : null;
  const projectIdRaw = searchParams?.get(SEARCH_PARAM_NAMES.PROJECT_ID);
  const projectId = projectIdRaw ? parseInt(projectIdRaw) : null;
  const ltiContextId =
    searchParams?.get(SEARCH_PARAM_NAMES.LTI_CONTEXT_ID) ?? null;
  const ltiCanvasCourseNodeId =
    searchParams?.get(SEARCH_PARAM_NAMES.LTI_CANVAS_COURSE_NODE_ID) ?? null;
  const requestedTutorTab = searchParams?.get(SEARCH_PARAM_NAMES.TUTOR_TAB);
  const showInstructorTabs = isEmbedded && isInstructor && projectId !== null;
  const activeTutorTab =
    showInstructorTabs &&
    (requestedTutorTab === "insights" || requestedTutorTab === "knowledge")
      ? requestedTutorTab
      : "chat";

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
  // the History modal to only conversations with this course's tutors.
  const courseTutorsSwrKey = ltiContextId
    ? `/api/auth/lti/tutors-for-course?context_id=${encodeURIComponent(
        ltiContextId
      )}`
    : null;
  const { data: courseTutors, isLoading: isLoadingCourseTutors } = useSWR<
    MinimalPersonaSnapshot[]
  >(courseTutorsSwrKey, errorHandlingFetcher);
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
  const courseTutorNameById = useMemo(() => {
    if (!courseTutors) return null;
    return new Map(courseTutors.map((t) => [t.id, t.name]));
  }, [courseTutors]);
  const isFirstTutorSetupScreen =
    ltiContextId !== null &&
    assistantId === null &&
    courseTutors !== undefined &&
    courseTutors.length === 0;
  const canManageCourseTutors =
    isInstructor || Boolean(courseConnectorStatus?.setup);
  const showTutorSidebar = ltiContextId !== null && !isFirstTutorSetupScreen;
  const isStudentWithSoleTutor =
    !canManageCourseTutors && courseTutors?.length === 1;
  const showTutorsSidebarTab = !isStudentWithSoleTutor;
  const tutorChatSessionsOptions = useMemo<
    UseChatSessionsOptions | undefined
  >(() => {
    if (projectId === null) {
      return undefined;
    }

    return {
      projectId,
      onlyNonProjectChats: false,
    };
  }, [projectId]);

  const {
    chatSessions,
    refreshChatSessions,
    currentChatSession,
    currentChatSessionId,
    isLoading: isLoadingChatSessions,
    hasMore: hasMoreChatSessions,
    isLoadingMore: isLoadingMoreChatSessions,
    loadMore: loadMoreChatSessions,
  } = useChatSessions(tutorChatSessionsOptions);
  const { currentMessageFiles, setCurrentMessageFiles } = useProjectsContext();

  // Find the tutor agent
  const tutorAgent = useMemo(() => {
    if (!assistantId || agents.length === 0) return null;
    return agents.find((a) => a.id === assistantId) ?? null;
  }, [assistantId, agents]);

  const { setSelectedAgentFromId, liveAgent } = useAgentController({
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
    chatSessionsOptions: tutorChatSessionsOptions,
  });

  const { onMessageSelection, currentSessionFileTokenCount } =
    useChatSessionController({
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
    if (isEmbedded) params.set(SEARCH_PARAM_NAMES.EMBEDDED, "true");
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
  }, [
    router,
    isEmbedded,
    assistantId,
    projectId,
    ltiContextId,
    ltiCanvasCourseNodeId,
  ]);

  // Manage tutors: jump back to the picker for the current course.
  const handleManageTutors = useCallback(() => {
    if (!ltiContextId) return;
    const params = new URLSearchParams();
    if (isEmbedded) params.set(SEARCH_PARAM_NAMES.EMBEDDED, "true");
    params.set(SEARCH_PARAM_NAMES.LTI_CONTEXT_ID, ltiContextId);
    if (projectId) params.set(SEARCH_PARAM_NAMES.PROJECT_ID, String(projectId));
    if (ltiCanvasCourseNodeId)
      params.set(
        SEARCH_PARAM_NAMES.LTI_CANVAS_COURSE_NODE_ID,
        ltiCanvasCourseNodeId
      );
    router.push(`/tutor?${params.toString()}`);
  }, [router, isEmbedded, ltiContextId, projectId, ltiCanvasCourseNodeId]);

  // Select a session from history
  const handleSelectSession = useCallback(
    (session: ChatSession) => {
      const params = new URLSearchParams();
      if (isEmbedded) params.set(SEARCH_PARAM_NAMES.EMBEDDED, "true");
      params.set(SEARCH_PARAM_NAMES.CHAT_ID, session.id);
      if (session.persona_id) {
        params.set(SEARCH_PARAM_NAMES.PERSONA_ID, String(session.persona_id));
      } else if (assistantId) {
        params.set(SEARCH_PARAM_NAMES.PERSONA_ID, String(assistantId));
      }
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
    [
      router,
      isEmbedded,
      assistantId,
      projectId,
      ltiContextId,
      ltiCanvasCourseNodeId,
    ]
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

  // Toggle history modal
  const toggleHistory = useCallback(() => {
    setHistoryOpen((prev) => !prev);
  }, []);

  const handleTutorTabChange = useCallback(
    (tab: "chat" | "insights" | "knowledge") => {
      const params = new URLSearchParams(searchParams?.toString());
      if (isEmbedded) params.set(SEARCH_PARAM_NAMES.EMBEDDED, "true");
      if (tab === "chat") {
        params.delete(SEARCH_PARAM_NAMES.TUTOR_TAB);
      } else {
        params.set(SEARCH_PARAM_NAMES.TUTOR_TAB, tab);
      }
      router.replace(`/tutor?${params.toString()}`, { scroll: false });
    },
    [router, searchParams, isEmbedded]
  );

  const handleHistoryFromSidebar = useCallback(() => {
    if (activeTutorTab !== "chat") {
      handleTutorTabChange("chat");
    }
    toggleHistory();
  }, [activeTutorTab, handleTutorTabChange, toggleHistory]);

  const renderWithInstructorShell = useCallback(
    (content: ReactNode) => {
      if (!showTutorSidebar) {
        return content;
      }

      return (
        <div className="flex h-full w-full bg-background-tint-01">
          <div className="flex h-full w-[3.25rem] shrink-0 flex-col gap-2 border-r border-border-01 bg-background-tint-02 px-2 py-3">
            <SidebarTab
              folded
              icon={SvgPlus}
              disabled={assistantId === null}
              onClick={handleNewConversation}
            >
              New Chat
            </SidebarTab>
            <SidebarTab
              folded
              icon={SvgHistory}
              disabled={assistantId === null}
              selected={historyOpen}
              onClick={handleHistoryFromSidebar}
            >
              History
            </SidebarTab>
            {showTutorsSidebarTab && (
              <SidebarTab
                folded
                icon={SvgUsers}
                selected={activeTutorTab === "chat" && assistantId === null}
                onClick={handleManageTutors}
              >
                Tutors
              </SidebarTab>
            )}
            {showInstructorTabs && (
              <>
                <SidebarTab
                  folded
                  icon={SvgBookOpen}
                  selected={activeTutorTab === "knowledge"}
                  onClick={() => handleTutorTabChange("knowledge")}
                >
                  Knowledge
                </SidebarTab>
                <SidebarTab
                  folded
                  icon={SvgBarChart}
                  selected={activeTutorTab === "insights"}
                  onClick={() => handleTutorTabChange("insights")}
                >
                  Insights
                </SidebarTab>
              </>
            )}
          </div>
          <div className="min-h-0 flex-1">{content}</div>
        </div>
      );
    },
    [
      activeTutorTab,
      assistantId,
      handleHistoryFromSidebar,
      handleManageTutors,
      handleNewConversation,
      handleTutorTabChange,
      historyOpen,
      showInstructorTabs,
      showTutorSidebar,
      showTutorsSidebarTab,
    ]
  );

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

  if (isFirstTutorSetupScreen && ltiContextId !== null) {
    return (
      <TutorPickerView
        ltiContextId={ltiContextId}
        projectId={projectId}
        ltiCanvasCourseNodeId={ltiCanvasCourseNodeId}
        canManageTutors={canManageCourseTutors}
      />
    );
  }

  if (activeTutorTab === "insights" && projectId !== null) {
    return renderWithInstructorShell(
      <TutorInstructorInsights projectId={projectId} />
    );
  }

  if (activeTutorTab === "knowledge" && projectId !== null) {
    return renderWithInstructorShell(
      <TutorInstructorKnowledge courseId={ltiContextId} />
    );
  }

  // No agentId chosen yet — render the picker if we know the course context,
  // otherwise fall back to the legacy no-agent state.
  if (!assistantId) {
    if (ltiContextId) {
      return renderWithInstructorShell(
        <TutorPickerView
          ltiContextId={ltiContextId}
          projectId={projectId}
          ltiCanvasCourseNodeId={ltiCanvasCourseNodeId}
          canManageTutors={canManageCourseTutors}
        />
      );
    }
    if (!isLoadingAgents) {
      return renderWithInstructorShell(<TutorNoAgent />);
    }
  }

  // We have an agentId but the agent itself failed to resolve.
  if (!effectiveAgent && !isLoadingAgents) {
    return renderWithInstructorShell(<TutorNoAgent />);
  }

  const hasMessages = currentChatSessionId && messageHistory.length > 0;
  const hasStarterMessages =
    (effectiveAgent?.starter_messages?.length ?? 0) > 0;
  const isHistoryLoading =
    isLoadingChatSessions ||
    (projectId === null && ltiContextId !== null && isLoadingCourseTutors);

  return renderWithInstructorShell(
    <>
      <TutorHistoryPanel
        open={historyOpen}
        sessions={chatSessions}
        currentSessionId={currentChatSessionId}
        allowedPersonaIds={courseTutorIds}
        personaNameById={courseTutorNameById}
        isLoading={isHistoryLoading}
        hasMore={hasMoreChatSessions}
        isLoadingMore={isLoadingMoreChatSessions}
        onLoadMore={loadMoreChatSessions}
        onSelectSession={handleSelectSession}
        onClose={() => setHistoryOpen(false)}
      />

      <div className="flex h-full w-full">
        {/* Main chat area */}
        <div className="flex flex-col flex-1 min-w-0">
          {!showTutorSidebar && (
            <TutorChatHeader
              agent={effectiveAgent ?? null}
              courseName={courseName}
              onNewConversation={handleNewConversation}
              onToggleHistory={toggleHistory}
              historyOpen={historyOpen}
              onManageTutors={
                canManageCourseTutors && ltiContextId
                  ? handleManageTutors
                  : null
              }
            />
          )}

          <Dropzone
            onDrop={(files) => handleMessageSpecificFileUpload(files)}
            noClick
          >
            {({ getRootProps }) => (
              <div
                className={`flex-1 flex flex-col items-center min-h-0 outline-none ${
                  showTutorSidebar ? "pt-3" : ""
                }`}
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
                      currentSessionFileTokenCount={
                        currentSessionFileTokenCount
                      }
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
    </>
  );
}
