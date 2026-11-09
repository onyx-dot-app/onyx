"use client";

import { usePathname, useSearchParams } from "@opal/navigation";
import { useState } from "react";
import { CRAFT_PATH } from "@/app/craft/v1/constants";
import { useBuildSessionController } from "@/app/craft/hooks/useBuildSessionController";
import { CRAFT_SEARCH_PARAM_NAMES } from "@/app/craft/services/searchParams";
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
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const urlSessionId = searchParams.get(CRAFT_SEARCH_PARAM_NAMES.SESSION_ID);
  // A navigation writes the next page's URL before that page renders, while
  // this one is still mounted. Follow the URL only while it names this page,
  // so leaving does not read as "no session" (clearing it, pre-provisioning).
  const [sessionId, setSessionId] = useState(urlSessionId);
  if (pathname === CRAFT_PATH && urlSessionId !== sessionId) {
    setSessionId(urlSessionId);
  }

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
