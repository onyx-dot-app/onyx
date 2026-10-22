"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useFilePreview } from "@/lib/build/hooks";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  createStaticPreview,
  downloadArtifactFile,
} from "@/app/craft/services/apiServices";
import { FilePreviewLoading } from "@/app/craft/components/output-panel/FilePreviewLoading";
import { PreviewUnavailable } from "@/app/craft/components/output-panel/PreviewUnavailable";
import type { FilePreviewContentProps } from "@/app/craft/components/output-panel/FilePreviewContent";

export default function HtmlFilePreview({
  sessionId,
  filePath,
  revision,
  refreshKey = 0,
  isActive = true,
  onRefreshingChange,
}: FilePreviewContentProps) {
  const t = useTranslations("craft.filePreview");
  const [retry, setRetry] = useState(0);
  const { data, error } = useFilePreview(
    SWR_KEYS.buildSessionArtifactFile(sessionId, filePath),
    () => createStaticPreview(sessionId, filePath),
    { revision, refreshKey: refreshKey + retry, isActive, onRefreshingChange }
  );
  useEffect(() => {
    if (!data || !isActive) return;
    const timer = setTimeout(
      () => setRetry((value) => value + 1),
      Math.max(0, data.expiresAt - Date.now() - 60_000)
    );
    return () => clearTimeout(timer);
  }, [data, isActive]);
  if (error)
    return (
      <PreviewUnavailable
        fileName={filePath}
        title={t("error.title")}
        description={t("error.description")}
        onRetry={() => setRetry((value) => value + 1)}
        onDownload={() => downloadArtifactFile(sessionId, filePath)}
      />
    );
  if (!data) return <FilePreviewLoading />;
  return (
    <iframe
      title={filePath.split("/").pop() || filePath}
      src={data.url}
      sandbox="allow-scripts"
      referrerPolicy="no-referrer"
      className="h-full w-full border-0 bg-background-neutral-01"
    />
  );
}
