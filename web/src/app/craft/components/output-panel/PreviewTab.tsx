"use client";

import { useState, useEffect } from "react";
import { cn } from "@opal/utils";
import { Text } from "@opal/components";
import { Section } from "@/layouts/general-layouts";
import { SvgGlobe, SvgLoader } from "@opal/icons";

/**
 * "unknown" - webapp-info hasn't loaded yet for this session.
 * "none" - webapp-info loaded, no webapp has ever been scaffolded.
 * "starting" - webapp scaffolded (has_webapp) but not yet serving.
 * "ready" - server has been observed ready at least once (latched).
 */
export type WebappState = "unknown" | "none" | "starting" | "ready";

interface PreviewTabProps {
  webappUrl: string | null;
  webappState: WebappState;
  /** Changing this value forces the iframe to fully remount / reload */
  refreshKey?: number;
}

/**
 * PreviewTab - Shows the webapp iframe preview
 *
 * States:
 * - "unknown": Shows blank dark background while SWR fetches
 * - "none": Shows an empty state (no web app in this session yet)
 * - "starting": Shows a spinner state while the dev server boots
 * - "ready": Shows iframe with crossfade from blank background
 */
export default function PreviewTab({
  webappUrl,
  webappState,
  refreshKey,
}: PreviewTabProps) {
  const [iframeLoaded, setIframeLoaded] = useState(false);

  // Reset loaded state when URL or refreshKey changes
  useEffect(() => {
    setIframeLoaded(false);
  }, [webappUrl, refreshKey]);

  if (webappState === "none") {
    return (
      <div className="h-full flex flex-col">
        <div className="flex-1 p-3 relative">
          <Section
            height="full"
            alignItems="center"
            justifyContent="center"
            gap={0.5}
            padding={2}
            className="rounded-b-08 bg-neutral-950"
          >
            <SvgGlobe size={48} className="stroke-text-inverted-02" />
            <Text font="heading-h3" color="text-inverted-03">
              No web app in this session yet
            </Text>
            <Text font="secondary-body" color="text-inverted-02">
              A live preview appears here once a web app is running.
            </Text>
          </Section>
        </div>
      </div>
    );
  }

  if (webappState === "starting") {
    return (
      <div className="h-full flex flex-col">
        <div className="flex-1 p-3 relative">
          <Section
            height="full"
            alignItems="center"
            justifyContent="center"
            gap={0.5}
            padding={2}
            className="rounded-b-08 bg-neutral-950"
          >
            <SvgLoader
              size={48}
              className="stroke-text-inverted-02 motion-safe:animate-spin"
            />
            <Text font="heading-h3" color="text-inverted-03">
              Starting the dev server...
            </Text>
            <Text font="secondary-body" color="text-inverted-02">
              Installing dependencies and booting. This usually takes under a
              minute.
            </Text>
          </Section>
        </div>
      </div>
    );
  }

  // Base background shown while loading ("unknown") or transitioning to ready
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
