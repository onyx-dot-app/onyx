"use client";

import { useCallback } from "react";
import { useBuildContext } from "@/app/build/contexts/BuildContext";
import { useBuildSession } from "@/app/build/hooks/useBuildSession";
import { BuildFile } from "@/app/build/contexts/UploadFilesContext";
import { useLlmManager } from "@/lib/hooks";
import Text from "@/refresh-components/texts/Text";
import Logo from "@/refresh-components/Logo";
import IconButton from "@/refresh-components/buttons/IconButton";
import { SvgSidebar } from "@opal/icons";
import InputBar from "@/app/build/components/InputBar";
import BuildWelcome from "@/app/build/components/BuildWelcome";

/**
 * BuildChatPanel - Center panel containing the chat interface
 *
 * Handles:
 * - Welcome state (no session)
 * - Message list (when session exists)
 * - Input bar at bottom
 * - Header with output panel toggle
 */
export default function BuildChatPanel() {
  const { outputPanelOpen, toggleOutputPanel } = useBuildContext();
  const { hasSession, isRunning, startSession, sendMessage } =
    useBuildSession();
  const llmManager = useLlmManager();

  const handleSubmit = useCallback(
    async (message: string, _files: BuildFile[]) => {
      // TODO: Pass files to session/message when API supports it
      if (hasSession) {
        await sendMessage(message);
      } else {
        await startSession(message);
      }
    },
    [hasSession, sendMessage, startSession]
  );

  return (
    <div className="flex flex-col h-full w-full">
      {/* Chat header */}
      <div className="flex flex-row items-center justify-between px-4 py-3 border-b border-border-01">
        <div className="flex flex-row items-center gap-2">
          <Logo folded size={24} />
          <Text headingH3 text05>
            Build
          </Text>
        </div>
        {hasSession && (
          <div className="flex flex-row items-center gap-2">
            <IconButton
              icon={SvgSidebar}
              onClick={toggleOutputPanel}
              tertiary
              tooltip={outputPanelOpen ? "Hide panel" : "Show panel"}
            />
          </div>
        )}
      </div>

      {/* Main content area */}
      <div className="flex-1 overflow-auto">
        {!hasSession ? (
          <BuildWelcome
            onSubmit={handleSubmit}
            isRunning={isRunning}
            llmManager={llmManager}
          />
        ) : (
          // TODO: Render BuildMessageList when session exists
          <div className="p-4">
            <Text secondaryBody text03>
              Message list will appear here
            </Text>
          </div>
        )}
      </div>

      {/* Input bar at bottom when session exists */}
      {hasSession && (
        <div className="px-4 pb-4 pt-2 border-t border-border-01">
          <div className="max-w-2xl mx-auto">
            <InputBar
              onSubmit={handleSubmit}
              isRunning={isRunning}
              placeholder="Continue the conversation..."
              llmManager={llmManager}
            />
          </div>
        </div>
      )}
    </div>
  );
}
