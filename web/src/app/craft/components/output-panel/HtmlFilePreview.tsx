"use client";

import { Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { useEffect, useRef, useState } from "react";
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
  const renewal = useRef<
    | {
        token: string;
        expiresAt: number;
        revision: typeof revision;
        refreshKey: number;
      }
    | undefined
  >(undefined);
  const [retry, setRetry] = useState(0);
  const { data, error } = useFilePreview(
    SWR_KEYS.buildSessionArtifactFile(sessionId, filePath),
    () => {
      const token =
        renewal.current &&
        renewal.current.revision === revision &&
        renewal.current.refreshKey === refreshKey &&
        renewal.current.expiresAt > Date.now()
          ? renewal.current.token
          : undefined;
      return token
        ? createStaticPreview(sessionId, filePath, token)
        : createStaticPreview(sessionId, filePath);
    },
    {
      revision,
      refreshKey: refreshKey + retry,
      // Retained frames remain live even when their tab is hidden.
      onRefreshingChange: isActive ? onRefreshingChange : undefined,
    }
  );
  useEffect(() => {
    if (!data) return;
    const timer = setTimeout(
      () => {
        renewal.current = {
          token: data.token,
          expiresAt: data.expiresAt,
          revision,
          refreshKey,
        };
        setRetry((value) => value + 1);
      },
      Math.max(0, data.expiresAt - Date.now() - 60_000)
    );
    return () => clearTimeout(timer);
  }, [data, revision, refreshKey]);
  if (error && !data)
    return (
      <PreviewUnavailable
        fileName={filePath}
        title={t("error.title")}
        description={t("error.description")}
        onRetry={() => {
          renewal.current = undefined;
          setRetry((value) => value + 1);
        }}
        onDownload={() => downloadArtifactFile(sessionId, filePath)}
      />
    );
  if (!data) return <FilePreviewLoading />;
  return (
    <Section gap={0} alignItems="stretch" justifyContent="start">
      {error && (
        <div
          role="alert"
          className="shrink-0 bg-background-neutral-00 px-4 py-2"
        >
          <Text font="secondary-body" color="text-03">
            {t("error.inline", { message: error.message })}
          </Text>
        </div>
      )}
      <div className="min-h-0 flex-1">
        <iframe
          title={filePath.split("/").pop() || filePath}
          src={data.url}
          sandbox="allow-scripts"
          referrerPolicy="no-referrer"
          className="h-full w-full border-0 bg-background-neutral-01"
        />
      </div>
    </Section>
  );
}
