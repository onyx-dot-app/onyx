"use client";

import { useTranslations } from "next-intl";
import { useCallback, type ReactNode } from "react";
import { SWRConfig } from "swr";
import { useUser } from "@/providers/UserProvider";
import { useFilePreview } from "@/lib/build/hooks";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  downloadArtifactFile,
  fetchFileContent,
} from "@/app/craft/services/apiServices";
import { Button, Text } from "@opal/components";
import { SvgDownloadCloud } from "@opal/icons";
import { WorkspaceHome } from "@/app/craft/components/output-panel/WorkspaceHome";
import ImagePreview from "@/app/craft/components/output-panel/ImagePreview";
import MarkdownFilePreview from "@/app/craft/components/output-panel/MarkdownFilePreview";
import PptxPreview from "@/app/craft/components/output-panel/PptxPreview";
import PdfPreview from "@/app/craft/components/output-panel/PdfPreview";

import {
  FilePreviewScrollArea,
  type FilePreviewScrollPosition,
} from "@/app/craft/components/output-panel/FilePreviewScrollArea";

import { CsvPreview } from "@/app/craft/components/output-panel/CsvPreview";

interface FilePreviewContentProps extends FilePreviewScrollPosition {
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
  if (!user) return null;
  // The retained viewer owns its bytes. Eviction or an identity change releases its cache.
  return (
    <SWRConfig
      key={`${user.id}:${sessionId}:${filePath}`}
      value={{ provider: () => new Map() }}
    >
      {/\.pptx?$/i.test(filePath) ? (
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
  const downloadTranslations = useTranslations("craft.filesTab");
  const { data, error, isLoading } = useFilePreview(
    SWR_KEYS.buildSessionArtifactFile(sessionId, filePath),
    () => fetchFileContent(sessionId, filePath),
    { revision, refreshKey, isActive, onRefreshingChange }
  );

  if (!data || data.error) {
    let title: string | undefined;
    let description = t("noContent.label");
    if (isLoading) {
      description = t("loading.label");
    } else if (error) {
      title = t("error.title");
      description = error.message;
    } else if (data?.error) {
      title = t("cannotPreview.title");
      description =
        data.error === "unsupported_binary"
          ? t("unsupported.description")
          : t("imageTooLarge.description");
    }
    const message = (
      <div className="flex flex-col items-center gap-3 text-center">
        <Text font="secondary-body" color="text-03">
          {description}
        </Text>
        {data?.error && !isLoading && !error && (
          <Button
            icon={SvgDownloadCloud}
            prominence="secondary"
            size="sm"
            onClick={() => downloadArtifactFile(sessionId, filePath)}
          >
            {downloadTranslations("download.label")}
          </Button>
        )}
      </div>
    );
    return (
      <WorkspaceHome title={title ?? description}>
        {title && message}
      </WorkspaceHome>
    );
  }

  const fileName = filePath.split("/").pop() || filePath;
  let viewer: ReactNode;
  if (data.isImage) {
    viewer = <ImagePreview src={data.content} fileName={fileName} />;
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
    <div className="flex h-full flex-col">
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
    </div>
  );
}
