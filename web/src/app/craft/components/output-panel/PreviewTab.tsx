"use client";

import { useState, useEffect } from "react";
import { cn } from "@/lib/utils";

interface PreviewTabProps {
  webappUrl: string | null;
  /** Changing this value forces the iframe to fully remount / reload */
  refreshKey?: number;
}

/**
 * PreviewTab - Shows the webapp iframe preview
 *
 * States:
 * - No webapp URL yet: Shows blank dark background while SWR fetches
 * - Has webapp URL: Shows iframe with crossfade from blank background
 */
export default function PreviewTab({ webappUrl, refreshKey }: PreviewTabProps) {
  const [iframeLoaded, setIframeLoaded] = useState(false);

  // Reset loaded state when URL or refreshKey changes
  useEffect(() => {
    setIframeLoaded(false);
  }, [webappUrl, refreshKey]);

  // Base background shown while loading or when no webapp exists yet
  return (
    <div className="h-full flex flex-col">
      <div className="flex-1 p-3 relative">
        {/* Base dark background - always present, visible when no iframe or iframe loading */}
        <div
          className={cn(
            "absolute inset-0 rounded-b-08 bg-neutral-950",
            "transition-opacity duration-300",
            iframeLoaded ? "opacity-0 pointer-events-none" : "opacity-100"
          )}
        />

        {/* Iframe - fades in when loaded */}
        {webappUrl && (
          <iframe
            key={refreshKey}
            src={webappUrl}
            onLoad={() => setIframeLoaded(true)}
            className={cn(
              "absolute inset-0 w-full h-full rounded-b-08 bg-neutral-950",
              "transition-opacity duration-300",
              iframeLoaded ? "opacity-100" : "opacity-0"
            )}
            sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox allow-top-navigation-by-user-activation"
            title="Web App Preview"
          />
        )}
      </div>
    </div>
  );
}
