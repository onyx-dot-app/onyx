"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import Button from "@/refresh-components/buttons/Button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";
import MinimalMarkdown from "@/components/chat/MinimalMarkdown";
import IconButton from "@/refresh-components/buttons/IconButton";
import Modal from "@/refresh-components/Modal";
import Text from "@/refresh-components/texts/Text";
import {
  SvgDownloadCloud,
  SvgFileText,
  SvgX,
  SvgZoomIn,
  SvgZoomOut,
} from "@opal/icons";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import ScrollIndicatorDiv from "@/refresh-components/ScrollIndicatorDiv";
import { cn } from "@/lib/utils";
export interface TextViewProps {
  presentingDocument: MinimalOnyxDocument;
  onClose: () => void;
}

export default function TextView({
  presentingDocument,
  onClose,
}: TextViewProps) {
  const [zoom, setZoom] = useState(100);
  const [fileContent, setFileContent] = useState("");
  const [fileUrl, setFileUrl] = useState("");
  const [fileName, setFileName] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [fileType, setFileType] = useState("application/octet-stream");
  const csvData = useMemo(() => {
    if (!fileType.startsWith("text/csv")) {
      return null;
    }

    const lines = fileContent.split(/\r?\n/).filter((l) => l.length > 0);
    const headers = lines.length > 0 ? lines[0]?.split(",") ?? [] : [];
    const rows = lines.slice(1).map((line) => line.split(","));

    return { headers, rows } as { headers: string[]; rows: string[][] };
  }, [fileContent, fileType]);

  // Detect if a given MIME type is one of the recognized markdown formats
  const isMarkdownFormat = (mimeType: string): boolean => {
    const markdownFormats = [
      "text/markdown",
      "text/x-markdown",
      "text/plain",
      "text/csv",
      "text/x-rst",
      "text/x-org",
      "txt",
    ];
    return markdownFormats.some((format) => mimeType.startsWith(format));
  };

  const isImageFormat = (mimeType: string) => {
    const imageFormats = [
      "image/png",
      "image/jpeg",
      "image/gif",
      "image/svg+xml",
    ];
    return imageFormats.some((format) => mimeType.startsWith(format));
  };
  // Detect if a given MIME type can be rendered in an <iframe>
  const isSupportedIframeFormat = (mimeType: string): boolean => {
    const supportedFormats = [
      "application/pdf",
      "image/png",
      "image/jpeg",
      "image/gif",
      "image/svg+xml",
    ];
    return supportedFormats.some((format) => mimeType.startsWith(format));
  };

  const fetchFile = useCallback(
    async (signal?: AbortSignal) => {
      setIsLoading(true);
      setLoadError(null);
      setFileContent("");
      const fileIdLocal =
        presentingDocument.document_id.split("__")[1] ||
        presentingDocument.document_id;

      try {
        const response = await fetch(
          `/api/chat/file/${encodeURIComponent(fileIdLocal)}`,
          {
            method: "GET",
            signal,
            cache: "force-cache",
          }
        );

        if (!response.ok) {
          setLoadError("Failed to load document.");
          return;
        }

        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        setFileUrl((prev) => {
          if (prev) {
            window.URL.revokeObjectURL(prev);
          }
          return url;
        });

        const originalFileName =
          presentingDocument.semantic_identifier || "document";
        setFileName(originalFileName);

        let contentType =
          response.headers.get("Content-Type") || "application/octet-stream";

        // If it's octet-stream but file name suggests a text-based extension, override accordingly
        if (contentType === "application/octet-stream") {
          const lowerName = originalFileName.toLowerCase();
          if (lowerName.endsWith(".md") || lowerName.endsWith(".markdown")) {
            contentType = "text/markdown";
          } else if (lowerName.endsWith(".txt")) {
            contentType = "text/plain";
          } else if (lowerName.endsWith(".csv")) {
            contentType = "text/csv";
          }
        }
        setFileType(contentType);

        // If the final content type looks like markdown, read its text
        if (isMarkdownFormat(contentType)) {
          const text = await blob.text();
          setFileContent(text);
        }
      } catch (error) {
        // Abort is expected on unmount / doc change
        if (signal?.aborted) {
          return;
        }
        setLoadError("Failed to load document.");
      } finally {
        // Prevent stale/aborted requests from clobbering the loading state.
        // This is especially important in React StrictMode where effects can run twice.
        if (!signal?.aborted) {
          setIsLoading(false);
        }
      }
    },
    [presentingDocument]
  );

  useEffect(() => {
    const controller = new AbortController();
    fetchFile(controller.signal);
    return () => {
      controller.abort();
    };
  }, [fetchFile]);

  useEffect(() => {
    return () => {
      if (fileUrl) {
        window.URL.revokeObjectURL(fileUrl);
      }
    };
  }, [fileUrl]);

  const handleDownload = () => {
    const link = document.createElement("a");
    link.href = fileUrl;
    link.download = fileName || presentingDocument.document_id;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const handleZoomIn = () => setZoom((prev) => Math.min(prev + 25, 200));
  const handleZoomOut = () => setZoom((prev) => Math.max(prev - 25, 100));

  return (
    <Modal
      open
      onOpenChange={(open) => {
        if (!open) {
          onClose();
        }
      }}
    >
      <Modal.Content
        large
        preventAccidentalClose={false}
        onOpenAutoFocus={(e) => e.preventDefault()}
      >
        <div className="relative flex flex-row items-center gap-2 p-4 shadow-01">
          <SvgFileText className="w-[1.5rem] h-[1.5rem] stroke-text-04 shrink-0" />
          <Text as="p" className="flex-1 min-w-0 truncate" mainUiBody>
            {fileName || "Document"}
          </Text>
          <div className="flex flex-row items-center justify-end gap-1">
            <IconButton
              internal
              onClick={handleZoomOut}
              icon={SvgZoomOut}
              tooltip="Zoom Out"
            />
            <Text as="p" text03 mainUiBody>
              {zoom}%
            </Text>
            <IconButton
              internal
              onClick={handleZoomIn}
              icon={SvgZoomIn}
              tooltip="Zoom In"
            />
            <IconButton
              internal
              onClick={handleDownload}
              icon={SvgDownloadCloud}
              tooltip="Download"
            />
            <IconButton
              internal
              onClick={onClose}
              icon={SvgX}
              tooltip="Close"
            />
          </div>
        </div>

        <Modal.Body>
          {isLoading ? (
            <div className="flex flex-col items-center justify-center flex-1 min-h-0 p-6 gap-4">
              <SimpleLoader className="h-8 w-8" />
              <Text as="p" text03 mainUiBody>
                Loading document...
              </Text>
            </div>
          ) : loadError ? (
            <div className="flex flex-col items-center justify-center flex-1 min-h-0 p-6 gap-4">
              <Text as="p" text03 mainUiBody>
                {loadError}
              </Text>
              <Button onClick={handleDownload}>Download File</Button>
            </div>
          ) : (
            <div
              className="flex flex-col flex-1 min-h-0 min-w-0 w-full transform origin-center transition-transform duration-300 ease-in-out"
              style={{ transform: `scale(${zoom / 100})` }}
            >
              {isImageFormat(fileType) ? (
                <img
                  src={fileUrl}
                  alt={fileName}
                  className="w-full flex-1 min-h-0 object-contain object-center"
                />
              ) : isSupportedIframeFormat(fileType) ? (
                <iframe
                  src={`${fileUrl}#toolbar=0`}
                  className="w-full h-full flex-1 min-h-0 border-none"
                  title="File Viewer"
                />
              ) : isMarkdownFormat(fileType) ? (
                <ScrollIndicatorDiv
                  className="flex-1 min-h-0 p-4"
                  variant="shadow"
                >
                  {csvData ? (
                    <Table>
                      <TableHeader className="sticky top-0 z-sticky">
                        <TableRow className="bg-background-tint-02">
                          {csvData.headers.map((h, i) => (
                            <TableHead key={i}>
                              <Text
                                as="p"
                                className="line-clamp-2 font-medium"
                                text03
                                mainUiBody
                              >
                                {h}
                              </Text>
                            </TableHead>
                          ))}
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {csvData.rows.map((row, rIdx) => (
                          <TableRow key={rIdx}>
                            {csvData.headers.map((_, cIdx) => (
                              <TableCell
                                key={cIdx}
                                className={cn(
                                  cIdx === 0 &&
                                    "sticky left-0 bg-background-tint-01",
                                  "py-0 px-4 whitespace-normal break-words"
                                )}
                              >
                                {row?.[cIdx] ?? ""}
                              </TableCell>
                            ))}
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  ) : (
                    <MinimalMarkdown
                      content={fileContent}
                      className="w-full pb-4 h-full text-lg break-words"
                    />
                  )}
                </ScrollIndicatorDiv>
              ) : (
                <div className="flex flex-col items-center justify-center flex-1 min-h-0 p-6 gap-4">
                  <Text as="p" text03 mainUiBody>
                    This file format is not supported for preview.
                  </Text>
                  <Button onClick={handleDownload}>Download File</Button>
                </div>
              )}
            </div>
          )}
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}
