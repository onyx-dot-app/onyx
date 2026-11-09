"use client";

import { useTranslations } from "next-intl";
import { Button } from "@opal/components";
import { IllustrationContent, Section } from "@opal/layouts";
import { SvgDownloadCloud } from "@opal/icons";
import type { RichStr } from "@opal/types";
import { getFileIcon } from "@/lib/utils";

interface PreviewUnavailableProps {
  fileName: string;
  title: string | RichStr;
  description: string | RichStr;
  onDownload: () => void;
  onRetry?: () => void;
}

export function PreviewUnavailable({
  fileName,
  title,
  description,
  onDownload,
  onRetry,
}: PreviewUnavailableProps) {
  const t = useTranslations("craft.filePreview");
  const FileIcon = getFileIcon(fileName);
  return (
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
          className="rounded-2xl bg-background-neutral-02"
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
              {t("retry.label")}
            </Button>
          )}
          <Button
            icon={SvgDownloadCloud}
            prominence="primary"
            size="lg"
            onClick={onDownload}
          >
            {t("download.label")}
          </Button>
        </Section>
      </Section>
    </Section>
  );
}
