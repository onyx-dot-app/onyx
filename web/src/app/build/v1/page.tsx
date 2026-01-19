"use client";

import { cn } from "@/lib/utils";
import { useBuildContext } from "@/app/build/contexts/BuildContext";
import { useBuildSession } from "@/app/build/hooks/useBuildSession";
import BuildChatPanel from "@/app/build/components/ChatPanel";
import BuildOutputPanel from "@/app/build/components/OutputPanel";

/**
 * Build V1 Page - Skeleton pattern for the 3-panel build interface
 *
 * This page uses the new architecture:
 * - BuildContext for UI state (sidebar visibility, panel states)
 * - useBuildSession hook for session data (will connect to APIs when ready)
 * - BuildChatPanel for the center chat interface
 * - BuildOutputPanel for the right preview/files/artifacts panel
 */
export default function BuildV1Page() {
  const { outputPanelOpen, toggleOutputPanel } = useBuildContext();
  const { hasSession } = useBuildSession();

  return (
    <div className="flex flex-row flex-1 h-full">
      {/* Center panel - Chat */}
      <div
        className={cn(
          "flex-1 h-full transition-all duration-300",
          outputPanelOpen && hasSession ? "w-1/2" : "w-full"
        )}
      >
        <BuildChatPanel />
      </div>

      {/* Right panel - Output (Preview, Files, Artifacts) */}
      {outputPanelOpen && hasSession && (
        <div className="w-1/2 border-l border-border-01 h-full">
          <BuildOutputPanel onClose={toggleOutputPanel} />
        </div>
      )}
    </div>
  );
}
