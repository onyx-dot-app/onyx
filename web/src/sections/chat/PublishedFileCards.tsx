"use client";

import { createContext, useContext, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { AttachmentItemButton, Card, useCreateModal } from "@opal/components";
import PreviewModal from "@/sections/modals/PreviewModal";
import type { MinimalOnyxDocument } from "@/lib/search/types";
import {
  filesSharingALabel,
  publishedFileLabel,
  publishedFilePath,
} from "@/lib/chat/publishedFiles";
import { Section } from "@opal/layouts";
import { codeSpan, markdown, stripBidiControls } from "@opal/utils";
import type { PublishedFile } from "@/app/app/services/streamingModels";
import { buildImgUrl } from "@/app/app/components/files/images/utils";
import { DownloadButton } from "@/sections/file-preview/DownloadButton";
import { useFormatBytes } from "@/hooks/useFormatBytes";
import { getFileIcon } from "@/lib/utils";

/**
 * Opens a published file's preview in the chat's Files panel. The chat page
 * and the shared view provide it; a page without the panel (NRF) does not,
 * and its cards preview in a modal.
 */
export const PublishedFileOpenerContext = createContext<
  ((file: PublishedFile) => void) | null
>(null);

interface PublishedFileCardsProps {
  files: PublishedFile[];
}

// A name's extension as a type label, only when it is ASCII letters and
// digits once bidi controls are stripped: the model chose the name, and other
// characters could reorder the description's line
function fileTypeLabel(fileName: string): string {
  const name = stripBidiControls(fileName);
  const dot = name.lastIndexOf(".");
  const extension = dot > 0 ? name.slice(dot + 1) : "";
  return /^[a-z0-9]+$/i.test(extension) ? extension.toUpperCase() : "";
}

/**
 * A download card for each file the model published. A click opens the
 * file's preview: in the Files panel when the page has one, else in a modal.
 */
export function PublishedFileCards({ files }: PublishedFileCardsProps) {
  const t = useTranslations("chat.publishedFiles");
  const formatBytes = useFormatBytes();
  const panelOpener = useContext(PublishedFileOpenerContext);
  const previewModal = useCreateModal();
  const [previewing, setPreviewing] = useState<PublishedFile | null>(null);
  const open =
    panelOpener ??
    ((file: PublishedFile) => {
      setPreviewing(file);
      previewModal.toggle(true);
    });
  // Stable per file: PreviewModal refetches when this object changes
  const presentingDocument = useMemo<MinimalOnyxDocument>(
    () => ({
      document_id: previewing?.file_id ?? "",
      semantic_identifier: previewing?.name ?? "",
    }),
    [previewing]
  );

  const sharingALabel = useMemo(() => filesSharingALabel(files), [files]);

  return (
    <Section gap={0.5} alignItems="start" height="fit">
      <previewModal.Provider>
        {previewing && (
          <PreviewModal
            presentingDocument={presentingDocument}
            onClose={() => previewModal.toggle(false)}
          />
        )}
      </previewModal.Provider>
      {files.map((file) => (
        <div key={file.file_id} className="w-full max-w-md">
          <Card padding={0} border="solid">
            <AttachmentItemButton
              icon={getFileIcon(file.name)}
              // A flex item: stripped, not isolated
              title={publishedFileLabel(file)}
              // The path tells cards of one shown name apart. Its code span
              // is an LTR isolate, so it cannot reorder the type and size.
              description={markdown(
                [
                  sharingALabel.has(file.file_id)
                    ? codeSpan(publishedFilePath(file))
                    : "",
                  fileTypeLabel(file.name),
                  formatBytes(file.size),
                ]
                  .filter(Boolean)
                  .join(" · ")
              )}
              aria-label={t("card.preview.ariaLabel", {
                name: stripBidiControls(file.name),
              })}
              onClick={() => open(file)}
              rightChildren={
                <DownloadButton
                  fileUrl={buildImgUrl(file.file_id)}
                  fileName={file.name}
                />
              }
            />
          </Card>
        </div>
      ))}
    </Section>
  );
}
