"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";
import Modal from "@/refresh-components/Modal";
import Text from "@/refresh-components/texts/Text";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import { Section } from "@/layouts/general-layouts";
import FloatingFooter from "@/sections/modals/PreviewModal/FloatingFooter";
import mime from "mime";
import {
  getCodeLanguage,
  getDataLanguage,
  getLanguageByMime,
} from "@/lib/languages";
import { fetchChatFile } from "@/lib/chat/svc";
import { PreviewContext } from "@/sections/modals/PreviewModal/interfaces";
import { resolveVariant } from "@/sections/modals/PreviewModal/variants";

interface PreviewModalProps {
  presentingDocument: MinimalOnyxDocument;
  onClose: () => void;
}

export default function PreviewModal({
  presentingDocument,
  onClose,
}: PreviewModalProps) {
  const [fileContent, setFileContent] = useState("");
  const [fileUrl, setFileUrl] = useState("");
  const [fileName, setFileName] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [mimeType, setMimeType] = useState("application/octet-stream");
  const [zoom, setZoom] = useState(100);

  const variant = useMemo(
    () => resolveVariant(presentingDocument.semantic_identifier, mimeType),
    [presentingDocument.semantic_identifier, mimeType]
  );

  const language = useMemo(
    () =>
      getCodeLanguage(presentingDocument.semantic_identifier || "") ||
      getLanguageByMime(mimeType) ||
      getDataLanguage(presentingDocument.semantic_identifier || "") ||
      "plaintext",
    [mimeType, presentingDocument.semantic_identifier]
  );

  const lineCount = useMemo(() => {
    if (!fileContent) return 0;
    return fileContent.split("\n").length;
  }, [fileContent]);

  const fileSize = useMemo(() => {
    if (!fileContent) return "";
    const bytes = new TextEncoder().encode(fileContent).length;
    if (bytes < 1024) return `${bytes} B`;
    const kb = bytes / 1024;
    if (kb < 1024) return `${kb.toFixed(2)} KB`;
    const mb = kb / 1024;
    return `${mb.toFixed(2)} MB`;
  }, [fileContent]);

  const fetchFile = useCallback(async () => {
    setIsLoading(true);
    setLoadError(null);
    setFileContent("");
    const fileIdLocal =
      presentingDocument.document_id.split("__")[1] ||
      presentingDocument.document_id;

    try {
      const response = await fetchChatFile(fileIdLocal);

      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      setFileUrl((prev) => {
        if (prev) window.URL.revokeObjectURL(prev);
        return url;
      });

      const originalFileName =
        presentingDocument.semantic_identifier || "document";
      setFileName(originalFileName);

      const rawContentType =
        response.headers.get("Content-Type") || "application/octet-stream";
      const resolvedMime =
        rawContentType === "application/octet-stream"
          ? mime.getType(originalFileName) ?? rawContentType
          : rawContentType;
      setMimeType(resolvedMime);

      const resolved = resolveVariant(
        presentingDocument.semantic_identifier,
        resolvedMime
      );
      if (resolved.needsTextContent) {
        setFileContent(await blob.text());
      }
    } catch {
      setLoadError("Failed to load document.");
    } finally {
      setIsLoading(false);
    }
  }, [presentingDocument]);

  useEffect(() => {
    fetchFile();
  }, [fetchFile]);

  useEffect(() => {
    return () => {
      if (fileUrl) window.URL.revokeObjectURL(fileUrl);
    };
  }, [fileUrl]);

  const handleZoomIn = useCallback(
    () => setZoom((prev) => Math.min(prev + 25, 200)),
    []
  );
  const handleZoomOut = useCallback(
    () => setZoom((prev) => Math.max(prev - 25, 25)),
    []
  );

  const ctx: PreviewContext = useMemo(
    () => ({
      fileContent,
      fileUrl,
      fileName,
      language,
      lineCount,
      fileSize,
      zoom,
      onZoomIn: handleZoomIn,
      onZoomOut: handleZoomOut,
    }),
    [
      fileContent,
      fileUrl,
      fileName,
      language,
      lineCount,
      fileSize,
      zoom,
      handleZoomIn,
      handleZoomOut,
    ]
  );

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
          title={fileName || "Document"}
          description={variant.headerDescription(ctx)}
          onClose={onClose}
        />

        {/* Body — uses flex-1/min-h-0/overflow-hidden (not Modal.Body)
            so that child ScrollIndicatorDivs become the actual scroll
            container instead of the body stealing it via overflow-y-auto. */}
        <div className="flex flex-col flex-1 min-h-0 overflow-hidden w-full bg-background-tint-01">
          {isLoading ? (
            <Section>
              <SimpleLoader className="h-8 w-8" />
            </Section>
          ) : loadError ? (
            <Section padding={1}>
              <Text text03 mainUiBody>
                {loadError}
              </Text>
            </Section>
          ) : (
            variant.renderContent(ctx)
          )}
        </div>

        {!isLoading && !loadError && (
          <FloatingFooter
            left={variant.renderFooterLeft(ctx)}
            right={variant.renderFooterRight(ctx)}
            codeBackground={variant.codeBackground}
          />
        )}
      </Modal.Content>
    </Modal>
  );
}
