"use client";

import { useSearchParams } from "next/navigation";
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
    <div className="relative flex-1 h-full overflow-hidden">
      {/* Chat panel - always full width for background */}
      <BuildChatPanel existingSessionId={sessionId} />

      {/* Output panel - floats over as a card */}
      <BuildOutputPanel onClose={toggleOutputPanel} isOpen={outputPanelOpen} />
    </div>
  );
}
