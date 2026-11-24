"use client";

import { useTranslations } from "next-intl";
import { MinimalOnyxDocument } from "@/lib/search/types";
import { Modal, type ModalContentProps } from "@opal/components";
import { stripBidiControls } from "@opal/utils";
import { useFormatBytes } from "@/hooks/useFormatBytes";
import { useChatFilePreview } from "@/lib/filePreview/hooks";
import { resolveFilePreviewFormat } from "@/lib/filePreview/format";
import {
  FilePreviewBody,
  FilePreviewScope,
} from "@/sections/file-preview/FilePreview";

interface PreviewModalProps {
  presentingDocument: MinimalOnyxDocument;
  onClose: () => void;
}

interface PreviewModalContentProps extends PreviewModalProps {
  fileId: string;
}

function PreviewModalContent({
  presentingDocument,
  fileId,
  onClose,
}: PreviewModalContentProps) {
  const t = useTranslations("chat.filePreview");
  const formatBytes = useFormatBytes();
  const displayName =
    presentingDocument.semantic_identifier || t("header.fallbackTitle");
  const preview = useChatFilePreview(fileId, displayName);
  const { data } = preview;

  // Until the file loads, its name picks the size, so the modal rarely resizes
  const kind =
    data?.kind ??
    resolveFilePreviewFormat(displayName, "application/octet-stream").kind;
  const size: Required<Pick<ModalContentProps, "width" | "height">> =
    kind === "code"
      ? { width: "xl", height: "lg" }
      : kind === "unsupported" || kind === "tooLarge"
        ? { width: "xl", height: "full" }
        : { width: "full", height: "full" };

  let description = "";
  if (data?.kind === "code") {
    description =
      data.language === "plaintext"
        ? t("text.headerDescription", {
            lineCount: data.lineCount,
            fileSize: formatBytes(data.size),
          })
        : t("code.headerDescription", {
            language: data.language,
            lineCount: data.lineCount,
            fileSize: formatBytes(data.size),
          });
  } else if (data?.kind === "spreadsheet") {
    description = t("spreadsheet.headerDescription", {
      count: data.sheets.length,
    });
  }

  return (
    <Modal
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <Modal.Content
        width={size.width}
        height={size.height}
        preventAccidentalClose={false}
        onOpenAutoFocus={(e) => e.preventDefault()}
      >
        <Modal.Header
          title={
            stripBidiControls(data?.name ?? displayName) ||
            t("header.fallbackTitle")
          }
          description={description}
          onClose={onClose}
        />
        <FilePreviewBody preview={preview} fileName={displayName} />
      </Modal.Content>
    </Modal>
  );
}

/**
 * A chat file's preview in a modal, with its name and details as the title.
 * Another file gets its own preview scope, so the last file's bytes go.
 */
export default function PreviewModal(props: PreviewModalProps) {
  // A citation's document ID carries the file ID after its source prefix
  const fileId =
    props.presentingDocument.document_id.split("__")[1] ||
    props.presentingDocument.document_id;
  return (
    <FilePreviewScope key={fileId}>
      <PreviewModalContent {...props} fileId={fileId} />
    </FilePreviewScope>
  );
}
