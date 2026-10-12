"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";
import { SWRConfig } from "swr";
import { useFilePreview } from "@/lib/build/hooks";
import { SWR_KEYS } from "@/lib/swr-keys";
import { fetchFileContent } from "@/app/craft/services/apiServices";
import { Text } from "@opal/components";
import { cn } from "@opal/utils";
import { SvgFileText } from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import { CsvPreview } from "@/app/craft/components/output-panel/CsvPreview";
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
  const [accepted, setAccepted] = useState({
    sessionId,
    filePath,
    revision,
    refreshKey,
  });
  if (
    accepted.sessionId !== sessionId ||
    accepted.filePath !== filePath ||
    (isActive &&
      (accepted.revision !== revision || accepted.refreshKey !== refreshKey))
  ) {
    setAccepted({ sessionId, filePath, revision, refreshKey });
  }

  // The retained viewer owns its bytes. Eviction releases the entire cache.
  return (
    <SWRConfig
      key={`${sessionId}:${filePath}`}
      value={{ provider: () => new Map() }}
    >
      {/\.pptx?$/i.test(filePath) ? (
        <PptxPreview {...accepted} isActive={isActive} />
      ) : /\.pdf$/i.test(filePath) ? (
        <PdfPreview {...accepted} isActive={isActive} />
      ) : (
        <FetchedFilePreview
          {...accepted}
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
    revision,
    refreshKey,
    isActive
  );

  if (isLoading || error || !data || data.error) {
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
  if (data.isImage) {
    return <ImagePreview src={data.content} fileName={fileName} />;
  }
  if (/\.csv$/i.test(filePath)) {
    return <CsvPreview content={data.content} isActive={isActive} />;
  }
  if (/\.md$/i.test(filePath)) {
    return (
      <MarkdownFilePreview
        content={data.content}
        fileName={fileName}
        filePath={filePath}
        mimeType={data.mimeType ?? "text/plain"}
        isImage={false}
      />
    );
  }

  return (
    <div className={cn("p-4", fullHeight && "h-full overflow-auto")}>
      <pre className="font-mono text-sm text-text-04 whitespace-pre-wrap wrap-break-word">
        {data.content}
      </pre>
    </div>
  );
}
