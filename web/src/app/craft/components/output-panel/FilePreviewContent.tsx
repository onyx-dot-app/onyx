"use client";

import { useTranslations } from "next-intl";
import { useState, type ReactNode } from "react";
import { SWRConfig } from "swr";
import { useFilePreview } from "@/lib/build/hooks";
import { SWR_KEYS } from "@/lib/swr-keys";
import { fetchFileContent } from "@/app/craft/services/apiServices";
import { Text } from "@opal/components";
import { cn } from "@opal/utils";
import { IconLoader } from "@opal/loaders";
import { SvgFileText } from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import ImagePreview from "@/app/craft/components/output-panel/ImagePreview";
import MarkdownFilePreview from "@/app/craft/components/output-panel/MarkdownFilePreview";
import PptxPreview from "@/app/craft/components/output-panel/PptxPreview";
import PdfPreview from "@/app/craft/components/output-panel/PdfPreview";

interface FilePreviewContentProps {
  sessionId: string;
  filePath: string;
  fullHeight?: boolean;
  isActive?: boolean;
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
  fullHeight = true,
  isActive = true,
  revision,
  refreshKey,
}: FilePreviewContentProps) {
  // The retained viewer owns its bytes. Eviction releases the entire cache.
  return (
    <SWRConfig
      key={`${sessionId}:${filePath}`}
      value={{ provider: () => new Map() }}
    >
      {/\.pptx?$/i.test(filePath) ? (
        <PptxPreview
          sessionId={sessionId}
          filePath={filePath}
          revision={revision}
          refreshKey={refreshKey}
          isActive={isActive}
        />
      ) : /\.pdf$/i.test(filePath) ? (
        <PdfPreview
          sessionId={sessionId}
          filePath={filePath}
          revision={revision}
          refreshKey={refreshKey}
          isActive={isActive}
        />
      ) : (
        <FetchedFilePreview
          sessionId={sessionId}
          filePath={filePath}
          revision={revision}
          refreshKey={refreshKey}
          fullHeight={fullHeight}
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
  fullHeight,
  isActive,
  revision,
  refreshKey,
}: FilePreviewContentProps) {
  const t = useTranslations("craft.filePreview");
  const { data, error, isLoading } = useFilePreview(
    SWR_KEYS.buildSessionArtifactFile(sessionId, filePath),
    () => fetchFileContent(sessionId, filePath),
    { revision, refreshKey, isActive }
  );

  if (!data || data.error) {
    let title: string | undefined;
    let description = t("noContent.label");
    if (isLoading) {
      description = t("loading.label");
    } else if (error) {
      title = t("error.title");
      description = fullHeight
        ? error.message
        : t("error.inline", { message: error.message });
    } else if (data?.error) {
      title = t("cannotPreview.title");
      description = data.error;
    }
    const message = (
      <Text font="secondary-body" color={title ? "text-02" : "text-03"}>
        {description}
      </Text>
    );
    if (!fullHeight) {
      return (
        <div className={cn("p-4", data?.error && "text-center")}>{message}</div>
      );
    }
    return (
      <Section
        height="full"
        alignItems="center"
        justifyContent="center"
        padding={8}
      >
        {title && (
          <>
            <SvgFileText size={48} className="stroke-text-02" />
            <Text font="heading-h3" color="text-03">
              {title}
            </Text>
          </>
        )}
        <div className="text-center max-w-md">{message}</div>
      </Section>
    );
  }

  const fileName = filePath.split("/").pop() || filePath;
  let viewer: ReactNode;
  if (data.isImage) {
    viewer = <ImagePreview src={data.content} fileName={fileName} />;
  } else if (/\.md$/i.test(filePath)) {
    viewer = (
      <MarkdownFilePreview
        content={data.content}
        fileName={fileName}
        filePath={filePath}
        mimeType={data.mimeType ?? "text/plain"}
        isImage={false}
      />
    );
  } else {
    viewer = (
      <div className={cn("p-4", fullHeight && "h-full overflow-auto")}>
        <pre className="font-mono text-sm text-text-04 whitespace-pre-wrap wrap-break-word">
          {data.content}
        </pre>
      </div>
    );
  }
  const boundedViewer: boolean =
    fullHeight || data.isImage || /\.md$/i.test(filePath);
  return (
    <div className={cn("flex flex-col", boundedViewer && "h-full")}>
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
      <div className="relative min-h-0 flex-1">
        {viewer}
        {isLoading && (
          <div className="absolute top-2 end-2">
            <IconLoader aria-label={t("loading.label")} />
          </div>
        )}
      </div>
    </div>
  );
}
