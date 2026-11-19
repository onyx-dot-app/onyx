"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { AttachmentItemButton, Card, useCreateModal } from "@opal/components";
import { Section } from "@opal/layouts";
import { stripBidiControls } from "@opal/utils";
import type { PublishedFile } from "@/app/app/services/streamingModels";
import { buildImgUrl } from "@/app/app/components/files/images/utils";
import PreviewModal from "@/sections/modals/PreviewModal";
import { DownloadButton } from "@/sections/modals/PreviewModal/variants/shared";
import { useFormatBytes } from "@/hooks/useFormatBytes";
import { getFileIcon } from "@/lib/utils";
import type { MinimalOnyxDocument } from "@/lib/search/types";

export interface PublishedFileVersion extends PublishedFile {
  // 1 for the first file of its name, then 2, 3, ...
  version: number;
}

interface PublishedFileCardsProps {
  files: PublishedFileVersion[];
}

function fileTypeLabel(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot > 0 && dot < name.length - 1
    ? name.slice(dot + 1).toUpperCase()
    : "";
}

/**
 * A download card for each file the model published. A click previews the
 * file; HTML previews as source.
 */
export function PublishedFileCards({ files }: PublishedFileCardsProps) {
  const t = useTranslations("chat.publishedFiles");
  const formatBytes = useFormatBytes();
  const previewModal = useCreateModal();
  const [previewing, setPreviewing] = useState<PublishedFile | null>(null);

  // Stable per file: PreviewModal refetches when this object changes.
  const presentingDocument = useMemo<MinimalOnyxDocument>(
    () => ({
      document_id: previewing?.file_id ?? "",
      semantic_identifier: previewing?.name ?? "",
    }),
    [previewing]
  );

  return (
    <>
      <previewModal.Provider>
        {previewing && (
          <PreviewModal
            presentingDocument={presentingDocument}
            onClose={() => previewModal.toggle(false)}
          />
        )}
      </previewModal.Provider>

      <Section gap={0.5} alignItems="start" height="fit">
        {files.map((file) => {
          const details = [fileTypeLabel(file.name), formatBytes(file.size)]
            .filter(Boolean)
            .join(" · ");
          return (
            <div key={file.file_id} className="w-full max-w-md">
              <Card padding={0} border="solid">
                <AttachmentItemButton
                  icon={getFileIcon(file.name)}
                  // The title is its own flex item, so it cannot reorder
                  // the text around it.
                  title={stripBidiControls(file.title ?? file.name)}
                  description={
                    file.version > 1
                      ? t("card.updated.description", { details })
                      : details
                  }
                  aria-label={t("card.preview.ariaLabel", { name: file.name })}
                  onClick={() => {
                    setPreviewing(file);
                    previewModal.toggle(true);
                  }}
                  rightChildren={
                    <DownloadButton
                      fileUrl={buildImgUrl(file.file_id)}
                      fileName={file.name}
                    />
                  }
                />
              </Card>
            </div>
          );
        })}
      </Section>
    </>
  );
}
