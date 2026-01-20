"use client";

import { useSearchParams } from "next/navigation";
import { cn } from "@/lib/utils";
import { useBuildSessionController } from "@/app/build/hooks/useBuildSessionController";
import {
  useOutputPanelOpen,
  useToggleOutputPanel,
} from "@/app/build/hooks/useBuildSessionStore";
import { getSessionIdFromSearchParams } from "@/app/build/services/searchParams";
import BuildChatPanel from "@/app/build/components/ChatPanel";
import BuildOutputPanel from "@/app/build/components/OutputPanel";

/**
 * Build V1 Page - Entry point for builds
 *
 * URL: /build/v1 (new build)
 * URL: /build/v1?sessionId=xxx (existing session)
 *
 * Renders the 2-panel layout (chat + output) and handles session controller setup.
 */
export default function BuildV1Page() {
  const searchParams = useSearchParams();
  const sessionId = getSessionIdFromSearchParams(searchParams);

  const outputPanelOpen = useOutputPanelOpen();
  const toggleOutputPanel = useToggleOutputPanel();
  useBuildSessionController({ existingSessionId: sessionId });

  return (
    <div className="flex flex-row flex-1 h-full overflow-hidden">
      {/* Center panel - Chat */}
      <div
        className={cn(
          "h-full transition-all duration-300 ease-in-out",
          outputPanelOpen ? "w-1/2" : "w-full"
        )}
      >
        <BuildChatPanel />
      </div>

      {/* Right panel - Output (Preview, Files, Artifacts) */}
      <BuildOutputPanel onClose={toggleOutputPanel} isOpen={outputPanelOpen} />
    </div>
  );
}
