"use client";

import { useTranslations } from "next-intl";
import { useCallback, useState, type ReactNode } from "react";
import { FilePreviewLoading } from "@/app/craft/components/output-panel/FilePreviewLoading";
import { SWRConfig } from "swr";
import { useUser } from "@/providers/UserProvider";
import { useFilePreview } from "@/lib/build/hooks";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  downloadArtifactFile,
  fetchFileContent,
} from "@/app/craft/services/apiServices";
import { Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { PreviewUnavailable } from "@/app/craft/components/output-panel/PreviewUnavailable";
import { binaryPreviewKind } from "@/app/craft/services/filePreview";
import BinaryFilePreview from "@/app/craft/components/output-panel/BinaryFilePreview";
import { WorkspaceHome } from "@/app/craft/components/output-panel/WorkspaceHome";
import ImagePreview from "@/app/craft/components/output-panel/ImagePreview";
import MarkdownFilePreview from "@/app/craft/components/output-panel/MarkdownFilePreview";
import PptxPreview from "@/app/craft/components/output-panel/PptxPreview";
import HtmlFilePreview from "@/app/craft/components/output-panel/HtmlFilePreview";
import PdfPreview from "@/app/craft/components/output-panel/PdfPreview";

import {
  FilePreviewScrollArea,
  type FilePreviewScrollPosition,
} from "@/app/craft/components/output-panel/FilePreviewScrollArea";

import { CsvPreview } from "@/app/craft/components/output-panel/CsvPreview";

export interface FilePreviewContentProps extends FilePreviewScrollPosition {
  onRefreshingChange?: (isRefreshing: boolean) => void;
  initialSlide?: number;
  onSlideChange?: (slide: number) => void;
  sessionId: string;
  filePath: string;
  revision?: string;
  /** Changing this value forces the preview to reload its data */
  refreshKey?: number;
}

/**
 * Routes to the appropriate preview component based on file type.
 */
export function FilePreviewContent({
  sessionId,
  filePath,
  isActive = true,
  revision,
  refreshKey,
  onRefreshingChange,
  initialSlide,
  onSlideChange,
  initialScrollTop,
  onScrollTopChange,
}: FilePreviewContentProps) {
  const { user } = useUser();
  const onPdfPageChange = useCallback(
    (page: number) => onSlideChange?.(page - 1),
    [onSlideChange]
  );
  const binaryKind = binaryPreviewKind(filePath);
  if (!user) return null;
  // The retained viewer owns its bytes. Eviction or an identity change releases its cache.
  return (
    <SWRConfig
      key={`${user.id}:${sessionId}:${filePath}`}
      value={{ provider: () => new Map() }}
    >
      {filePath.startsWith("outputs/") && /\.html?$/i.test(filePath) ? (
        <HtmlFilePreview
          sessionId={sessionId}
          filePath={filePath}
          revision={revision}
          refreshKey={refreshKey}
          isActive={isActive}
          onRefreshingChange={onRefreshingChange}
        />
      ) : /\.pptx?$/i.test(filePath) ? (
        <PptxPreview
          sessionId={sessionId}
          filePath={filePath}
          revision={revision}
          refreshKey={refreshKey}
          initialSlide={initialSlide}
          onSlideChange={onSlideChange}
          isActive={isActive}
          onRefreshingChange={onRefreshingChange}
        />
      ) : /\.pdf$/i.test(filePath) ? (
        <PdfPreview
          sessionId={sessionId}
          filePath={filePath}
          revision={revision}
          refreshKey={refreshKey}
          initialPage={(initialSlide ?? 0) + 1}
          onPageChange={onPdfPageChange}
          isActive={isActive}
          onRefreshingChange={onRefreshingChange}
        />
      ) : binaryKind ? (
        <BinaryFilePreview
          kind={binaryKind}
          sessionId={sessionId}
          filePath={filePath}
          revision={revision}
          refreshKey={refreshKey}
          isActive={isActive}
          onRefreshingChange={onRefreshingChange}
          initialScrollTop={initialScrollTop}
          onScrollTopChange={onScrollTopChange}
        />
      ) : (
        <FetchedFilePreview
          sessionId={sessionId}
          filePath={filePath}
          revision={revision}
          refreshKey={refreshKey}
          onRefreshingChange={onRefreshingChange}
          initialScrollTop={initialScrollTop}
          onScrollTopChange={onScrollTopChange}
          isActive={isActive}
        />
      )}
    </SWRConfig>
  );
}

/** Fetch text or image content; unsupported text formats use a plain preview. */
function FetchedFilePreview({
  sessionId,
  filePath,
  isActive,
  revision,
  refreshKey,
  onRefreshingChange,
  initialScrollTop,
  onScrollTopChange,
}: FilePreviewContentProps) {
  const t = useTranslations("craft.filePreview");
  const [retry, setRetry] = useState(0);
  const { data, error, isLoading } = useFilePreview(
    SWR_KEYS.buildSessionArtifactFile(sessionId, filePath),
    () => fetchFileContent(sessionId, filePath),
    {
      revision,
      refreshKey: (refreshKey ?? 0) + retry,
      isActive,
      onRefreshingChange,
    }
  );

  if (!data || data.error) {
    if (isLoading && !error) return <FilePreviewLoading />;
    if (error || data?.error) {
      const reason = error
        ? "error"
        : data?.error === "image_too_large"
          ? "imageTooLarge"
          : "unsupported";
      return (
        <PreviewUnavailable
          fileName={filePath}
          title={t(
            reason === "unsupported"
              ? "cannotPreview.title"
              : reason === "imageTooLarge"
                ? "imageTooLarge.title"
                : "error.title"
          )}
          description={t(`${reason}.description`)}
          onDownload={() => downloadArtifactFile(sessionId, filePath)}
          onRetry={error ? () => setRetry((value) => value + 1) : undefined}
        />
      );
    }
    return <WorkspaceHome title={t("noContent.label")}>{null}</WorkspaceHome>;
  }

  const fileName = filePath.split("/").pop() || filePath;
  let viewer: ReactNode;
  if (data.isImage) {
    viewer = <ImagePreview src={data.content} fileName={fileName} />;
  } else if (/\.html?$/i.test(filePath)) {
    viewer = (
      <iframe
        title={fileName}
        srcDoc={data.content}
        sandbox="allow-scripts"
        referrerPolicy="no-referrer"
        className="h-full w-full border-0 bg-background-neutral-01"
      />
    );
  } else if (/\.csv$/i.test(filePath)) {
    viewer = (
      <CsvPreview
        content={data.content}
        initialScrollTop={initialScrollTop}
        onScrollTopChange={onScrollTopChange}
        isActive={isActive}
      />
    );
  } else if (/\.md$/i.test(filePath)) {
    viewer = (
      <MarkdownFilePreview
        initialScrollTop={initialScrollTop}
        onScrollTopChange={onScrollTopChange}
        isActive={isActive}
        content={data.content}
      />
    );
  } else {
    viewer = (
      <FilePreviewScrollArea
        initialScrollTop={initialScrollTop}
        onScrollTopChange={onScrollTopChange}
        isActive={isActive}
      >
        <pre className="font-mono text-sm text-text-04 whitespace-pre-wrap wrap-break-word">
          {data.content}
        </pre>
      </FilePreviewScrollArea>
    );
  }
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
      <div className="min-h-0 flex-1">{viewer}</div>
    </Section>
  );
}
