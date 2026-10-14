"use client";

import { useSearchParams } from "next/navigation";
import { useBuildSessionController } from "@/app/craft/hooks/useBuildSessionController";
import { getSessionIdFromSearchParams } from "@/app/craft/services/searchParams";
import CraftWorkspace from "@/app/craft/components/CraftWorkspace";
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

  useBuildSessionController({ existingSessionId: sessionId });

  return (
    // overflow-clip, not overflow-hidden: a hidden box is still programmatically
    // scrollable, which would shove the chat column off-screen.
    <div className="relative flex-1 min-w-0 h-full overflow-clip">
      <VideoBackground />

      <div className="relative z-10 w-full h-full">
        <CraftWorkspace existingSessionId={sessionId} />
      </div>
    </div>
  );
}
