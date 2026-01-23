"use client";

import { useCallback, useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import {
  useSession,
  useSessionId,
  useHasSession,
  useIsRunning,
  useOutputPanelOpen,
  useToggleOutputPanel,
  useBuildSessionStore,
  useIsPreProvisioning,
} from "@/app/build/hooks/useBuildSessionStore";
import { useBuildStreaming } from "@/app/build/hooks/useBuildStreaming";
import { BuildFile } from "@/app/build/contexts/UploadFilesContext";
import { uploadFile } from "@/app/build/services/apiServices";
import { BUILD_SEARCH_PARAM_NAMES } from "@/app/build/services/searchParams";
import { usePopup } from "@/components/admin/connectors/Popup";
import InputBar from "@/app/build/components/InputBar";
import BuildWelcome from "@/app/build/components/BuildWelcome";
import BuildMessageList from "@/app/build/components/BuildMessageList";
import SandboxStatusIndicator from "@/app/build/components/SandboxStatusIndicator";
import IconButton from "@/refresh-components/buttons/IconButton";
import { SvgSidebar } from "@opal/icons";
import { useBuildContext } from "@/app/build/contexts/BuildContext";
import useScreenSize from "@/hooks/useScreenSize";
import { cn } from "@/lib/utils";

interface BuildChatPanelProps {
  /** Session ID from URL - used to prevent welcome flash while loading */
  existingSessionId?: string | null;
}

/**
 * BuildChatPanel - Center panel containing the chat interface
 *
 * Handles:
 * - Welcome state (no session)
 * - Message list (when session exists)
 * - Input bar at bottom
 * - Header with output panel toggle
 */
export default function BuildChatPanel({
  existingSessionId,
}: BuildChatPanelProps) {
  const router = useRouter();
  const { popup, setPopup } = usePopup();
  const outputPanelOpen = useOutputPanelOpen();
  const session = useSession();
  const sessionId = useSessionId();
  const hasSession = useHasSession();
  const isRunning = useIsRunning();
  const { setLeftSidebarFolded, leftSidebarFolded } = useBuildContext();
  const { isMobile } = useScreenSize();
  const toggleOutputPanel = useToggleOutputPanel();

  // Track when output panel is fully closed (after animation completes)
  // This prevents the "open panel" button from appearing during the close animation
  const [isOutputPanelFullyClosed, setIsOutputPanelFullyClosed] =
    useState(!outputPanelOpen);

  useEffect(() => {
    if (outputPanelOpen) {
      // Panel opening - immediately mark as not fully closed
      setIsOutputPanelFullyClosed(false);
    } else {
      // Panel closing - wait for 300ms animation to complete
      const timer = setTimeout(() => setIsOutputPanelFullyClosed(true), 300);
      return () => clearTimeout(timer);
    }
  }, [outputPanelOpen]);

  // Access actions directly like chat does - these don't cause re-renders
  const consumePreProvisionedSession = useBuildSessionStore(
    (state) => state.consumePreProvisionedSession
  );
  const createNewSession = useBuildSessionStore(
    (state) => state.createNewSession
  );
  const createSession = useBuildSessionStore((state) => state.createSession);
  const appendMessageToCurrent = useBuildSessionStore(
    (state) => state.appendMessageToCurrent
  );
  const appendMessageToSession = useBuildSessionStore(
    (state) => state.appendMessageToSession
  );
  const refreshSessionHistory = useBuildSessionStore(
    (state) => state.refreshSessionHistory
  );
  const nameBuildSession = useBuildSessionStore(
    (state) => state.nameBuildSession
  );
  const { streamMessage } = useBuildStreaming();
  const isPreProvisioning = useIsPreProvisioning();

  const handleSubmit = useCallback(
    async (message: string, files: BuildFile[], demoDataEnabled: boolean) => {
      // TODO: Pass demoDataEnabled to createSession when backend is implemented
      console.log("Demo data enabled:", demoDataEnabled);
      if (hasSession && sessionId) {
        // Existing session flow
        // Check if response is still streaming - show toast like main chat does
        if (isRunning) {
          setPopup({
            message: "Please wait for the current operation to complete.",
            type: "error",
          });
          return;
        }

        // Add user message to state
        appendMessageToCurrent({
          id: `msg-${Date.now()}`,
          type: "user",
          content: message,
          timestamp: new Date(),
        });
        // Stream the response
        await streamMessage(sessionId, message);
      } else {
        // New session flow - get pre-provisioned session or fall back to creating new one
        const newSessionId = await consumePreProvisionedSession();

        if (!newSessionId) {
          // Fallback: createNewSession handles everything including navigation
          const fallbackSessionId = await createNewSession(message);
          if (fallbackSessionId) {
            if (files.length > 0) {
              await Promise.all(
                files
                  .filter((f) => f.file)
                  .map((f) => uploadFile(fallbackSessionId, f.file!))
              );
            }
            await streamMessage(fallbackSessionId, message);
          }
        } else {
          // Pre-provisioned session flow:
          // The backend session already exists (created during pre-provisioning).
          // Here we initialize the LOCAL Zustand store entry with the right state.
          const userMessage = {
            id: `msg-${Date.now()}`,
            type: "user" as const,
            content: message,
            timestamp: new Date(),
          };
          // Initialize local state (NOT an API call - backend session already exists)
          // - status: "running" disables input immediately
          // - isLoaded: false allows loadSession to fetch sandbox info while preserving messages
          createSession(newSessionId, {
            messages: [userMessage],
            status: "running",
          });

          // 2. Upload files before navigation
          if (files.length > 0) {
            await Promise.all(
              files
                .filter((f) => f.file)
                .map((f) => uploadFile(newSessionId, f.file!))
            );
          }

          // 3. Navigate to URL - session controller will set currentSessionId
          router.push(
            `/build/v1?${BUILD_SEARCH_PARAM_NAMES.SESSION_ID}=${newSessionId}`
          );

          // 4. Name the session and refresh history
          setTimeout(() => nameBuildSession(newSessionId), 200);
          await refreshSessionHistory();

          // 5. Stream the response (uses session ID directly, not currentSessionId)
          await streamMessage(newSessionId, message);
        }
      }
    },
    [
      hasSession,
      sessionId,
      isRunning,
      setPopup,
      appendMessageToCurrent,
      streamMessage,
      consumePreProvisionedSession,
      createNewSession,
      createSession,
      appendMessageToSession,
      refreshSessionHistory,
      nameBuildSession,
      router,
    ]
  );

  return (
    <div className="h-full w-full">
      {popup}
      {/* Content wrapper - shrinks when output panel opens */}
      <div
        className={cn(
          "flex flex-col h-full transition-all duration-300 ease-in-out",
          outputPanelOpen ? "w-1/2" : "w-full"
        )}
      >
        {/* Chat header */}
        <div className="flex flex-row items-center justify-between pl-4 pr-4 py-3">
          <div className="flex flex-row items-center gap-2">
            {/* Mobile sidebar toggle - only show on mobile when sidebar is folded */}
            {isMobile && leftSidebarFolded && (
              <IconButton
                icon={SvgSidebar}
                onClick={() => setLeftSidebarFolded(false)}
                internal
              />
            )}
            <SandboxStatusIndicator />
          </div>
          {/* Output panel toggle - only show when panel is fully closed (after animation) */}
          {isOutputPanelFullyClosed && (
            <IconButton
              icon={SvgSidebar}
              onClick={toggleOutputPanel}
              tooltip="Open output panel"
              tertiary
              className="!bg-background-tint-00 border rounded-full"
              iconClassName="!stroke-text-04"
            />
          )}
        </div>

        {/* Main content area */}
        <div className="flex-1 overflow-auto">
          {!hasSession && !existingSessionId ? (
            <BuildWelcome
              onSubmit={handleSubmit}
              isRunning={isRunning}
              sandboxInitializing={isPreProvisioning}
            />
          ) : (
            <BuildMessageList
              messages={session?.messages ?? []}
              streamItems={session?.streamItems ?? []}
              isStreaming={isRunning}
            />
          )}
        </div>

        {/* Input bar at bottom when session exists */}
        {(hasSession || existingSessionId) && (
          <div className="px-4 pb-8 pt-4">
            <div className="max-w-2xl mx-auto">
              <InputBar
                onSubmit={handleSubmit}
                isRunning={isRunning}
                placeholder="Continue the conversation..."
                sessionId={sessionId ?? undefined}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
