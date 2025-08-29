"use client";
import i18n from "@/i18n/init";
import k from "./../../i18n/keys";

import { useState, useEffect, useCallback } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Download, XIcon, ZoomIn, ZoomOut } from "lucide-react";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";
import MinimalMarkdown from "@/components/chat/MinimalMarkdown";

interface TextViewProps {
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
  const [fileType, setFileType] = useState("application/octet-stream");

  // Detect if a given MIME type is one of the recognized markdown formats
  const isMarkdownFormat = (mimeType: string): boolean => {
    const markdownFormats = [
      "text/markdown",
      "text/x-markdown",
      "text/plain",
      "text/x-rst",
      "text/x-org",
      "txt",
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document", // .docx
    ];

    // Special case: .docx is not a markdown format, but we want to support it for preview
    if (
      mimeType ===
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ) {
      return true;
    }

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
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document", // .docx
    ];

    return supportedFormats.some((format) => mimeType.startsWith(format));
  };

  const fetchFile = useCallback(async () => {
    setIsLoading(true);
    const fileId =
      presentingDocument.document_id.split("__")[1] ||
      presentingDocument.document_id;

    try {
      const response = await fetch(
        `/api/chat/file/${encodeURIComponent(fileId)}`,
        {
          method: "GET",
        }
      );
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      setFileUrl(url);

      const originalFileName =
        presentingDocument.semantic_identifier || "document";
      setFileName(originalFileName);

      let contentType =
        response.headers.get("Content-Type") || "application/octet-stream";

      // If it's octet-stream but file name suggests a markdown extension, override and attempt to read as markdown
      if (
        contentType === "application/octet-stream" &&
        (originalFileName.toLowerCase().endsWith(".md") ||
          originalFileName.toLowerCase().endsWith(".markdown"))
      ) {
        contentType = "text/markdown";
      }
      setFileType(contentType);

      // If the final content type looks like markdown, read its text
      if (isMarkdownFormat(contentType)) {
        const text = await blob.text();
        setFileContent(text);
      }
    } catch (error) {
      console.error("Error fetching file:", error);
    } finally {
      // Keep the slight delay for a smoother loading experience
      setTimeout(() => {
        setIsLoading(false);
      }, 1000);
    }
  }, [presentingDocument]);

  useEffect(() => {
    fetchFile();
  }, [fetchFile]);

  const handleDownload = () => {
    const link = document.createElement("a");
    link.href = fileUrl;
    link.download = presentingDocument.document_id || fileName;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const handleZoomIn = () => setZoom((prev) => Math.min(prev + 25, 200));
  const handleZoomOut = () => setZoom((prev) => Math.max(prev - 25, 100));

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent
        hideCloseIcon
        className="max-w-4xl w-[90vw] flex flex-col justify-between gap-y-0 h-full max-h-[80vh] p-0"
      >
        <DialogHeader className="px-4 mb-0 pt-2 pb-3 flex flex-row items-center justify-between border-b">
          <DialogTitle className="text-lg font-medium truncate">
            {fileName}
          </DialogTitle>

          <div className="flex items-center space-x-2">
            <Button variant="ghost" size="icon" onClick={handleZoomOut}>
              <ZoomOut className="h-4 w-4" />
              <span className="sr-only">{i18n.t(k.ZOOM_OUT)}</span>
            </Button>
            <span className="text-sm">
              {zoom}
              {i18n.t(k._15)}
            </span>
            <Button variant="ghost" size="icon" onClick={handleZoomIn}>
              <ZoomIn className="h-4 w-4" />
              <span className="sr-only">{i18n.t(k.ZOOM_IN)}</span>
            </Button>
            <Button variant="ghost" size="icon" onClick={handleDownload}>
              <Download className="h-4 w-4" />
              <span className="sr-only">{i18n.t(k.DOWNLOAD)}</span>
            </Button>
            <Button variant="ghost" size="icon" onClick={onClose}>
              <XIcon className="h-4 w-4" />
              <span className="sr-only">{i18n.t(k.CLOSE)}</span>
            </Button>
          </div>
        </DialogHeader>
        <div className="mt-0 rounded-b-lg flex-1 overflow-hidden">
          <div className="flex items-center justify-center w-full h-full">
            {isLoading ? (
              <div className="flex flex-col items-center justify-center h-full">
                <div className="animate-spin rounded-full h-16 w-16 border-t-4 border-b-4 border-primary"></div>
                <p className="mt-6 text-lg font-medium text-muted-foreground">
                  {i18n.t(k.LOADING_DOCUMENT)}
                </p>
              </div>
            ) : (
              <div
                className="w-full h-full transform origin-center transition-transform duration-300 ease-in-out"
                style={{ transform: `scale(${zoom / 100})` }}
              >
                {isImageFormat(fileType) ? (
                  <img
                    src={fileUrl}
                    alt={fileName}
                    className="w-full h-full object-contain object-center"
                  />
                ) : isSupportedIframeFormat(fileType) ? (
                  <iframe
                    src={`${fileUrl}#toolbar=0`}
                    className="w-full h-full border-none"
                    title="Просмотр файлов"
                  />
                ) : isMarkdownFormat(fileType) ? (
                  <div className="w-full h-full p-6 overflow-y-scroll overflow-x-hidden">
                    <MinimalMarkdown
                      content={fileContent}
                      className="w-full pb-4 h-full text-lg break-words"
                    />
                  </div>
                ) : (
                  <div className="flex flex-col items-center justify-center h-full">
                    <p className="text-lg font-medium text-muted-foreground">
                      {i18n.t(k.THIS_FILE_FORMAT_IS_NOT_SUPPOR)}
                    </p>
                    <Button className="mt-4" onClick={handleDownload}>
                      {i18n.t(k.DOWNLOAD_FILE)}
                    </Button>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
