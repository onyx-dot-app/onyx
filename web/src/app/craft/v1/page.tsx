"use client";

import { useSearchParams } from "next/navigation";
import { useBuildSessionController } from "@/app/craft/hooks/useBuildSessionController";
import { useOutputPanelOpen } from "@/app/craft/hooks/useBuildSessionStore";
import { getSessionIdFromSearchParams } from "@/app/craft/services/searchParams";
import BuildChatPanel from "@/app/craft/components/ChatPanel";
import BuildOutputPanel from "@/app/craft/components/OutputPanel";
import VideoBackground from "@/app/craft/components/video-background/VideoBackground";

/**
 * Build V1 Page - Entry point for builds
 *
 * URL: /craft/v1 (new build)
 * URL: /craft/v1?sessionId=xxx (existing session)
 *
 * Renders the 2-panel layout (chat + output) and handles session controller setup.
 */
export default function BuildV1Page() {
  const searchParams = useSearchParams();
  const sessionId = getSessionIdFromSearchParams(searchParams);

  const outputPanelOpen = useOutputPanelOpen();
  useBuildSessionController({ existingSessionId: sessionId });

  return (
    // overflow-clip, not overflow-hidden: a hidden box is still programmatically
    // scrollable, which would shove the chat column off-screen.
    <div className="relative flex-1 h-full overflow-clip">
      <VideoBackground />

      <div className="relative z-10 w-full h-full">
        <BuildChatPanel existingSessionId={sessionId} />
        <BuildOutputPanel isOpen={outputPanelOpen} />
      </div>
    </div>
  );
}
