"use client";

import { useState, useEffect } from "react";
import { useTranslations } from "next-intl";
import { cn } from "@opal/utils";
import { Text } from "@opal/components";
import { Section } from "@/layouts/general-layouts";
import { SvgGlobe, SvgLoader } from "@opal/icons";
import { type WebappState } from "@/app/craft/components/output-panel/interfaces";

interface PreviewTabProps {
  webappUrl: string | null;
  webappState: WebappState;
  /** Changing this value forces the iframe to fully remount / reload */
  refreshKey?: number;
}

/**
 * PreviewTab - Shows the webapp iframe preview
 */
export default function PreviewTab({
  webappUrl,
  webappState,
  refreshKey,
}: PreviewTabProps) {
  const t = useTranslations("craft.previewTab");
  const tOutput = useTranslations("craft.outputPanel");
  const [iframeLoaded, setIframeLoaded] = useState(false);

  // Reset loaded state when URL or refreshKey changes
  useEffect(() => {
    setIframeLoaded(false);
  }, [webappUrl, refreshKey]);

  if (webappState === "none") {
    return (
      <Section
        height="full"
        alignItems="center"
        justifyContent="center"
        padding={8}
      >
        <SvgGlobe size={48} className="stroke-text-02" aria-hidden />
        <Text font="heading-h3" color="text-03">
          {tOutput("noWebapp.label")}
        </Text>
        <Text font="secondary-body" color="text-02">
          {t("empty.description")}
        </Text>
      </Section>
    );
  }

  if (webappState === "starting") {
    return (
      <Section
        height="full"
        alignItems="center"
        justifyContent="center"
        padding={8}
        role="status"
      >
        <SvgLoader
          size={48}
          className="stroke-text-02 motion-safe:animate-spin"
          aria-hidden
        />
        <Text font="heading-h3" color="text-03">
          {t("starting.title")}
        </Text>
        <Text font="secondary-body" color="text-02">
          {t("starting.description")}
        </Text>
      </Section>
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
            title={t("frame.title")}
          />
        )}
      </div>
    </div>
  );
}
