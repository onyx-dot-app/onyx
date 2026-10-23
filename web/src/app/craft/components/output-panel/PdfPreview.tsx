"use client";

import { useRef, useEffect } from "react";
import { useFilePreview } from "@/lib/build/hooks";
import { FetchError } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { useTranslations } from "next-intl";
import { Text } from "@opal/components";
import { WorkspaceHome } from "@/app/craft/components/output-panel/WorkspaceHome";
import dynamic from "next/dynamic";
import {
  buildArtifactUrl,
  downloadArtifactFile,
} from "@/app/craft/services/apiServices";

const PdfDocumentViewer = dynamic(
  () => import("@/app/craft/components/output-panel/PdfDocumentViewer"),
  { ssr: false }
);

interface PdfPreviewProps {
  initialPage?: number;
  onPageChange?: (page: number) => void;
  onRefreshingChange?: (isRefreshing: boolean) => void;
  sessionId: string;
  filePath: string;
  revision?: string;
  refreshKey?: number;
  isActive?: boolean;
}

export default function PdfPreview({
  sessionId,
  filePath,
  revision,
  refreshKey,
  isActive = true,
  onRefreshingChange,
  initialPage,
  onPageChange,
}: PdfPreviewProps) {
  const t = useTranslations("craft.pdfPreview");
  const displayedBlobRef = useRef<Blob | null>(null);
  const { data: blob, error } = useFilePreview(
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
      const displayedBlob = displayedBlobRef.current;
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
        // Reuse the loaded document when an activation read returns identical bytes.
        if (
          new Uint8Array(displayedBytes).every(
            (byte, index) => byte === next[index]
          )
        )
          return displayedBlob;
      }
      return nextBlob;
    },
    { revision, refreshKey, isActive, onRefreshingChange }
  );

  useEffect(() => {
    displayedBlobRef.current = blob ?? null;
  }, [blob]);

  if (!blob)
    return (
      <WorkspaceHome title={t(error ? "error.title" : "loading.label")}>
        {error && (
          <Text font="secondary-body" color="text-03">
            {t("error.description")}
          </Text>
        )}
      </WorkspaceHome>
    );

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
      <div className="min-h-0 flex-1">
        <PdfDocumentViewer
          blob={blob}
          isActive={isActive}
          initialPage={initialPage}
          onPageChange={onPageChange}
          onDownload={() => downloadArtifactFile(sessionId, filePath)}
        />
      </div>
    </div>
  );
}
