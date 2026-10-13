"use client";

import { useState, useEffect } from "react";
import { useFilePreview } from "@/lib/build/hooks";
import { FetchError } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { useTranslations } from "next-intl";
import { cn } from "@opal/utils";
import { Text } from "@opal/components";
import { SvgFileText } from "@opal/icons";
import { IconLoader } from "@opal/loaders";
import { Section } from "@/layouts/general-layouts";
import { buildArtifactUrl } from "@/app/craft/services/apiServices";

interface PdfPreviewProps {
  sessionId: string;
  filePath: string;
  revision?: string;
  refreshKey?: number;
  isActive?: boolean;
}

/**
 * PdfPreview - Renders PDF files using the browser's built-in PDF viewer.
 * Fetches the PDF as a blob and creates an object URL so the iframe renders
 * it inline (the backend serves artifacts with Content-Disposition: attachment,
 * which would otherwise force a download).
 */
export default function PdfPreview({
  sessionId,
  filePath,
  revision,
  refreshKey,
  isActive = true,
}: PdfPreviewProps) {
  const t = useTranslations("craft.pdfPreview");
  const [objectUrl, setObjectUrl] = useState<{
    blob: Blob;
    url: string;
  } | null>(null);
  const {
    data: blob,
    error,
    isLoading,
  } = useFilePreview(
    SWR_KEYS.buildSessionArtifactFile(sessionId, filePath),
    async () => {
      const response = await fetch(buildArtifactUrl(sessionId, filePath), {
        cache: "no-store",
      });
      if (!response.ok)
        throw new FetchError(
          `Failed to fetch PDF: ${response.status}`,
          response.status,
          null
        );
      const nextBlob = await response.blob();
      const displayedBlob = objectUrl?.blob;
      if (
        revision === undefined &&
        displayedBlob &&
        displayedBlob.size === nextBlob.size &&
        displayedBlob.type === nextBlob.type
      ) {
        const [displayedBytes, nextBytes] = await Promise.all([
          displayedBlob.arrayBuffer(),
          nextBlob.arrayBuffer(),
        ]);
        const next = new Uint8Array(nextBytes);
        // Keep the iframe's URL when an activation read returns identical bytes.
        if (
          new Uint8Array(displayedBytes).every(
            (byte, index) => byte === next[index]
          )
        )
          return displayedBlob;
      }
      return nextBlob;
    },
    { revision, refreshKey, isActive }
  );

  // Object URLs belong only to the mounted viewer.
  useEffect(() => {
    if (!blob) {
      setObjectUrl(null);
      return;
    }
    const url = URL.createObjectURL(blob);
    setObjectUrl({ blob, url });
    return () => URL.revokeObjectURL(url);
  }, [blob]);
  const blobUrl = objectUrl?.blob === blob ? objectUrl?.url : undefined;

  if (error && !blob) {
    return (
      <Section
        height="full"
        alignItems="center"
        justifyContent="center"
        padding={8}
      >
        <SvgFileText size={48} className="stroke-text-02" />
        <Text font="heading-h3" color="text-03">
          {t("error.title")}
        </Text>
        <div className="text-center max-w-md">
          <Text font="secondary-body" color="text-02">
            {t("error.description")}
          </Text>
        </div>
      </Section>
    );
  }

  if ((!blob && isLoading) || !blobUrl) {
    return (
      <Section
        height="full"
        alignItems="center"
        justifyContent="center"
        padding={8}
      >
        <Text font="secondary-body" color="text-03">
          {t("loading.label")}
        </Text>
      </Section>
    );
  }

  return (
    <div className="flex h-full flex-col">
      {error && (
        <div
          role="alert"
          className="shrink-0 bg-background-neutral-00 px-4 py-2"
        >
          <Text font="secondary-body" color="text-03">
            {t("error.description")}
          </Text>
        </div>
      )}
      <div className="relative min-h-0 flex-1">
        <iframe
          src={blobUrl}
          title={filePath.split("/").pop() || t("frame.title")}
          className={cn("w-full h-full border-none")}
        />
        {isLoading && (
          <div className="absolute top-2 end-2">
            <IconLoader aria-label={t("loading.label")} />
          </div>
        )}
      </div>
    </div>
  );
}
