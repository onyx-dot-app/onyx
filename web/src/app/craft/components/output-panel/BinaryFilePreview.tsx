"use client";

import dynamic from "next/dynamic";
import { useState } from "react";
import { FilePreviewLoading } from "@/app/craft/components/output-panel/FilePreviewLoading";
import { useTranslations } from "next-intl";
import { Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { useFilePreview } from "@/lib/build/hooks";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  fetchBinaryPreview,
  type BinaryPreviewKind,
} from "@/app/craft/services/filePreview";
import { downloadArtifactFile } from "@/app/craft/services/apiServices";
import { PreviewUnavailable } from "@/app/craft/components/output-panel/PreviewUnavailable";
import MediaPreview from "@/app/craft/components/output-panel/MediaPreview";
import SpreadsheetPreview from "@/app/craft/components/output-panel/SpreadsheetPreview";
import type { FilePreviewContentProps } from "@/app/craft/components/output-panel/FilePreviewContent";

const DocxDocumentPreview = dynamic(
  () => import("@/app/craft/components/output-panel/DocxDocumentPreview"),
  { ssr: false }
);

interface BinaryFilePreviewProps extends FilePreviewContentProps {
  kind: BinaryPreviewKind;
}

export default function BinaryFilePreview({
  kind,
  sessionId,
  filePath,
  revision,
  refreshKey = 0,
  isActive = true,
  onRefreshingChange,
  ...scroll
}: BinaryFilePreviewProps) {
  const t = useTranslations("craft.filePreview");
  const [retry, setRetry] = useState(0);
  const [failedBlob, setFailedBlob] = useState<Blob>();
  const media = kind === "audio" || kind === "video";
  const limitMB = media ? 100 : 20;
  const { data, error } = useFilePreview(
    SWR_KEYS.buildSessionArtifactFile(sessionId, filePath),
    async () => {
      const result = await fetchBinaryPreview(
        sessionId,
        filePath,
        limitMB * 1024 * 1024
      );
      if (result.tooLarge) return { ...result, sheets: undefined };
      const sheets =
        kind === "spreadsheet"
          ? await (
              await import("@/lib/readSpreadsheetPreview")
            ).readSpreadsheetPreview(await result.blob.arrayBuffer())
          : undefined;
      return { ...result, sheets };
    },
    { revision, refreshKey: refreshKey + retry, isActive, onRefreshingChange }
  );
  const onDownload = () => downloadArtifactFile(sessionId, filePath);
  const onRetry = () => {
    setFailedBlob(undefined);
    setRetry((value) => value + 1);
  };
  if (!data) {
    return error ? (
      <PreviewUnavailable
        fileName={filePath}
        title={t("error.title")}
        description={t("error.description")}
        onDownload={onDownload}
        onRetry={onRetry}
      />
    ) : (
      <FilePreviewLoading />
    );
  }
  if (data.tooLarge)
    return (
      <PreviewUnavailable
        fileName={filePath}
        title={t("tooLarge.title")}
        description={t("tooLarge.description", { size: limitMB })}
        onDownload={onDownload}
      />
    );
  if (failedBlob === data.blob)
    return (
      <PreviewUnavailable
        fileName={filePath}
        title={t(media ? "playback.title" : "error.title")}
        description={t(media ? "playback.description" : "error.description")}
        onDownload={onDownload}
        onRetry={onRetry}
      />
    );
  const onError = () => setFailedBlob(data.blob);
  return (
    <Section gap={0} alignItems="stretch" justifyContent="start">
      {error && (
        <Text font="secondary-body" color="text-03">
          {t("error.description")}
        </Text>
      )}
      <div className="min-h-0 flex-1">
        {media ? (
          <MediaPreview
            blob={data.blob}
            kind={kind}
            fileName={filePath.split("/").pop() || filePath}
            isActive={isActive}
            onError={onError}
          />
        ) : data.sheets ? (
          <SpreadsheetPreview
            sheets={data.sheets}
            isActive={isActive}
            {...scroll}
          />
        ) : (
          <DocxDocumentPreview
            blob={data.blob}
            isActive={isActive}
            onError={onError}
            {...scroll}
          />
        )}
      </div>
    </Section>
  );
}
