"use client";

import { MinimalOnyxDocument } from "@/lib/search/types";
import { Modal } from "@opal/components";
import { stripBidiControls } from "@opal/utils";
import {
  ChatFilePreviewBody,
  useChatFilePreview,
} from "@/sections/modals/PreviewModal/ChatFilePreview";

interface PreviewModalProps {
  presentingDocument: MinimalOnyxDocument;
  onClose: () => void;
}

export default function PreviewModal({
  presentingDocument,
  onClose,
}: PreviewModalProps) {
  const preview = useChatFilePreview(presentingDocument);
  const { variant, ctx } = preview;

  return (
    <Modal
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <Modal.Content
        width={variant.width}
        height={variant.height}
        preventAccidentalClose={false}
        onOpenAutoFocus={(e) => e.preventDefault()}
      >
        <Modal.Header
          title={
            stripBidiControls(ctx.fileName) || ctx.t("header.fallbackTitle")
          }
          description={variant.headerDescription(ctx)}
          onClose={onClose}
        />
        <ChatFilePreviewBody preview={preview} />
      </Modal.Content>
    </Modal>
  );
}
