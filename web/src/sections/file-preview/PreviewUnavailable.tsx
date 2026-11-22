"use client";

import { useTranslations } from "next-intl";
import { Button } from "@opal/components";
import { IllustrationContent, Section } from "@opal/layouts";
import { SvgDownloadCloud } from "@opal/icons";
import type { RichStr } from "@opal/types";
import { getFileIcon } from "@/lib/utils";

interface PreviewUnavailableProps {
  fileName: string;
  fileUrl: string;
  title: string | RichStr;
  description: string | RichStr;
  onRetry?: () => void;
}

/** Stands in for a preview that cannot show: the file's icon, why, and a download. */
export function PreviewUnavailable({
  fileName,
  fileUrl,
  title,
  description,
  onRetry,
}: PreviewUnavailableProps) {
  const t = useTranslations("chat.filePreview");
  const FileIcon = getFileIcon(fileName);
  return (
    // The content centers with auto margins, so a short panel scrolls to its top
    <Section
      padding={6}
      gap={0}
      justifyContent="start"
      className="overflow-auto"
    >
      <Section height="auto" gap={0} className="my-auto max-w-2xl shrink-0">
        <Section
          width={5}
          height={5}
          gap={0}
          className="rounded-16 bg-background-neutral-02"
        >
          <FileIcon
            size={40}
            className="stroke-text-03 [&_*]:stroke-1"
            aria-hidden
          />
        </Section>
        <IllustrationContent
          size="lg"
          title={title}
          description={description}
        />
        <Section height="auto" flexDirection="row" gap={3} wrap>
          {onRetry && (
            <Button prominence="secondary" size="lg" onClick={onRetry}>
              {t("retryButton.label")}
            </Button>
          )}
          <Button
            href={fileUrl}
            download={fileName}
            icon={SvgDownloadCloud}
            prominence="primary"
            size="lg"
          >
            {t("downloadButton.label")}
          </Button>
        </Section>
      </Section>
    </Section>
  );
}
