"use client";

import { Section } from "@opal/layouts";
import { IconLoader } from "@opal/loaders";
import { memo, useState, useEffect, useCallback, useMemo } from "react";
import { useTranslations } from "next-intl";
import { MinimalOnyxDocument } from "@/lib/search/types";
import { Button, Text } from "@opal/components";

import FloatingFooter from "@/sections/modals/PreviewModal/FloatingFooter";
import mime from "mime";
import {
  getCodeLanguage,
  getDataLanguage,
  getLanguageByMime,
} from "@/lib/languages";
import { fetchChatFile } from "@/lib/chat/svc";
import type {
  PreviewContext,
  PreviewVariant,
} from "@/sections/modals/PreviewModal/interfaces";
import { resolveVariant } from "@/sections/modals/PreviewModal/variants";
import {
  parseContentDispositionFileName,
  withMimeTypeExtension,
} from "@/sections/modals/PreviewModal/downloadFileName";

/** A chat file's preview: its fetched content and the variant that shows it. */
export interface ChatFilePreview {
  variant: PreviewVariant;
  ctx: PreviewContext;
  isLoading: boolean;
  loadError: string | null;
}

/**
 * Fetches a chat file (`/api/chat/file/{id}`) for its preview. The preview
 * modal and the chat's Files panel both show files through it.
 */
export function useChatFilePreview(
  presentingDocument: MinimalOnyxDocument
): ChatFilePreview {
  const t = useTranslations("chat.modals.preview");
  const [fileContent, setFileContent] = useState("");
  const [fileUrl, setFileUrl] = useState("");
  const [fileName, setFileName] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [mimeType, setMimeType] = useState("application/octet-stream");
  const [zoom, setZoom] = useState(100);

  const variantName = fileName || presentingDocument.semantic_identifier;

  const variant = useMemo(
    () => resolveVariant(variantName, mimeType),
    [variantName, mimeType]
  );

  const language = useMemo(
    () =>
      getCodeLanguage(variantName || "") ||
      getLanguageByMime(mimeType) ||
      getDataLanguage(variantName || "") ||
      "plaintext",
    [mimeType, variantName]
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

  useEffect(() => {
    // A preview that closes or changes file while loading drops the load,
    // so it creates no object URL that nothing would revoke
    let current = true;
    void (async () => {
      setIsLoading(true);
      setLoadError(null);
      setFileContent("");
      const fileIdLocal =
        presentingDocument.document_id.split("__")[1] ||
        presentingDocument.document_id;
      const originalFileName =
        presentingDocument.semantic_identifier || "document";
      // Direct raw-file URL — usable for downloads without materializing a blob.
      const rawFileUrl = `/api/chat/file/${encodeURIComponent(fileIdLocal)}`;

      const updateFileUrl = (url: string) =>
        setFileUrl((prev) => {
          if (prev.startsWith("blob:")) window.URL.revokeObjectURL(prev);
          return url;
        });

      try {
        setFileName(originalFileName);

        // Variants that render from backend-parsed content (spreadsheets) don't
        // need the raw binary blob — skip downloading the full workbook and let
        // the download button point at the raw URL directly.
        const preResolved = resolveVariant(
          presentingDocument.semantic_identifier,
          "application/octet-stream"
        );
        if (preResolved.needsParsedContent) {
          updateFileUrl(rawFileUrl);
          setMimeType(
            mime.getType(originalFileName) ?? "application/octet-stream"
          );
          const parsedResponse = await fetchChatFile(fileIdLocal, true);
          const text = await parsedResponse.text();
          if (current) setFileContent(text);
          return;
        }

        const response = await fetchChatFile(fileIdLocal);
        if (!current) {
          await response.body?.cancel();
          return;
        }

        // The stored name and MIME from the response headers are authoritative;
        // re-resolve with them BEFORE materializing the body as a blob.
        const storedFileName =
          parseContentDispositionFileName(
            response.headers.get("Content-Disposition")
          ) ?? originalFileName;
        const rawContentType =
          response.headers.get("Content-Type") || "application/octet-stream";
        const resolvedMime =
          rawContentType === "application/octet-stream"
            ? (mime.getType(storedFileName) ?? rawContentType)
            : rawContentType;
        const resolvedFileName = withMimeTypeExtension(
          storedFileName,
          resolvedMime
        );
        setFileName(resolvedFileName);
        setMimeType(resolvedMime);

        const resolved = resolveVariant(resolvedFileName, resolvedMime);
        if (resolved.needsParsedContent) {
          // Name alone didn't identify a spreadsheet, but the stored MIME did
          // (e.g. an xlsx with a renamed/missing display name). Discard the raw
          // workbook body and render from the parsed payload instead.
          await response.body?.cancel();
          if (!current) return;
          updateFileUrl(rawFileUrl);
          const parsedResponse = await fetchChatFile(fileIdLocal, true);
          const text = await parsedResponse.text();
          if (current) setFileContent(text);
          return;
        }

        const blob = await response.blob();
        if (!current) return;
        updateFileUrl(window.URL.createObjectURL(blob));

        if (resolved.needsTextContent) {
          const text = await blob.text();
          if (current) setFileContent(text);
        }
      } catch (error) {
        console.error(
          `Failed to load preview for chat file ${fileIdLocal}:`,
          error
        );
        // Keep a usable download link for the CURRENT file even when the
        // preview itself failed (a stale previous-file URL must never win).
        if (!current) return;
        updateFileUrl(rawFileUrl);
        setLoadError(t("loadError.message"));
      } finally {
        if (current) setIsLoading(false);
      }
    })();
    return () => {
      current = false;
    };
  }, [presentingDocument, t]);

  useEffect(() => {
    return () => {
      if (fileUrl.startsWith("blob:")) window.URL.revokeObjectURL(fileUrl);
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
      t,
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
      t,
    ]
  );

  return useMemo(
    () => ({ variant, ctx, isLoading, loadError }),
    [variant, ctx, isLoading, loadError]
  );
}

interface ChatFilePreviewBodyProps {
  preview: ChatFilePreview;
}

/** The preview's content and its footer, below a header that the host draws. */
export const ChatFilePreviewBody = memo(function ChatFilePreviewBody({
  preview,
}: ChatFilePreviewBodyProps) {
  const { variant, ctx, isLoading, loadError } = preview;
  return (
    <>
      {/* Body — uses flex-1/min-h-0/overflow-hidden so that child
          ScrollIndicatorDivs become the actual scroll container. */}
      <Section
        gap={0}
        justifyContent="start"
        alignItems="stretch"
        height="auto"
        className="flex-1 min-h-0 overflow-hidden bg-background-tint-01"
      >
        {isLoading ? (
          <Section>
            <IconLoader className="h-8 w-8" />
          </Section>
        ) : loadError ? (
          <Section padding={4}>
            <Text font="main-ui-body" color="text-03">
              {loadError}
            </Text>
            {ctx.fileUrl && (
              <Button href={ctx.fileUrl} download={ctx.fileName}>
                {ctx.t("downloadButton.label")}
              </Button>
            )}
          </Section>
        ) : (
          variant.renderContent(ctx)
        )}
      </Section>

      {!isLoading && !loadError && (
        <FloatingFooter
          left={variant.renderFooterLeft(ctx)}
          right={variant.renderFooterRight(ctx)}
          codeBackground={variant.codeBackground}
        />
      )}
    </>
  );
});
