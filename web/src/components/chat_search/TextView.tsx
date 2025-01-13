"use client";

import { useState, useEffect, useCallback } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Download, XIcon, ZoomIn, ZoomOut } from "lucide-react";
import { OnyxDocument } from "@/lib/search/interfaces";
import { MinimalMarkdown } from "./MinimalMarkdown";

interface TextViewProps {
  presentingDocument: OnyxDocument;
  onClose: () => void;
}
export default function TextView({
  presentingDocument,
  onClose,
}: TextViewProps) {
  const [zoom, setZoom] = useState(100);
  const [fileContent, setFileContent] = useState<string>("");
  const [fileUrl, setFileUrl] = useState<string>("");
  const [fileName, setFileName] = useState<string>("");
  const [isLoading, setIsLoading] = useState(true);
  const [fileType, setFileType] = useState<string>("application/octet-stream");

  const isMarkdownFormat = (mimeType: string): boolean => {
    const markdownFormats = [
      "text/markdown",
      "text/x-markdown",
      "text/plain",
      "text/x-rst",
      "text/x-org",
    ];
    return markdownFormats.some((format) => mimeType.startsWith(format));
  };

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

  const fetchFile = useCallback(async () => {
    setIsLoading(true);
    const fileId = presentingDocument.document_id.split("__")[1];
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
      setFileName(presentingDocument.semantic_identifier || "document");
      const contentType =
        response.headers.get("Content-Type") || "application/octet-stream";
      setFileType(contentType);

      if (isMarkdownFormat(blob.type)) {
        const text = await blob.text();
        setFileContent(text);
      }
    } catch (error) {
      console.error("Error fetching file:", error);
    } finally {
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
    link.download = fileName;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const handleZoomIn = () => setZoom((prev) => Math.min(prev + 25, 200));
  const handleZoomOut = () => setZoom((prev) => Math.max(prev - 25, 100));

  return (
    <Dialog open={true} onOpenChange={onClose}>
      <DialogContent
        hideCloseIcon
        className="max-w-5xl w-[90vw] flex flex-col justify-between gap-y-0 h-full max-h-[80vh] p-0"
      >
        <DialogHeader className="px-4 mb-0 pt-2 pb-3 flex flex-row items-center justify-between border-b">
          <DialogTitle className="text-lg font-medium truncate">
            {fileName}
          </DialogTitle>
          <div className="flex items-center space-x-2">
            <Button variant="ghost" size="icon" onClick={handleZoomOut}>
              <ZoomOut className="h-4 w-4" />
              <span className="sr-only">Zoom Out</span>
            </Button>
            <span className="text-sm">{zoom}%</span>
            <Button variant="ghost" size="icon" onClick={handleZoomIn}>
              <ZoomIn className="h-4 w-4" />
              <span className="sr-only">Zoom In</span>
            </Button>
            <Button variant="ghost" size="icon" onClick={handleDownload}>
              <Download className="h-4 w-4" />
              <span className="sr-only">Download</span>
            </Button>
            <Button variant="ghost" size="icon" onClick={() => onClose()}>
              <XIcon className="h-4 w-4" />
              <span className="sr-only">Close</span>
            </Button>
          </div>
        </DialogHeader>
        <div className="mt-0 rounded-b-lg flex-1 overflow-hidden">
          <div className="flex items-center justify-center w-full h-full">
            {isLoading ? (
              <div className="flex flex-col items-center justify-center h-full">
                <div className="animate-spin rounded-full h-16 w-16 border-t-4 border-b-4 border-primary"></div>
                <p className="mt-6 text-lg font-medium text-muted-foreground">
                  Loading document...
                </p>
              </div>
            ) : (
              <div
                className={`w-full h-full transform origin-center transition-transform duration-300 ease-in-out`}
                style={{ transform: `scale(${zoom / 100})` }}
              >
                {isSupportedIframeFormat(fileType) ? (
                  <iframe
                    src={`${fileUrl}#toolbar=0`}
                    className="w-full h-full border-none"
                    title="File Viewer"
                  />
                ) : isMarkdownFormat(fileType) ? (
                  <div className="w-full h-full p-6 overflow-y-scroll overflow-x-hidden">
                    <MinimalMarkdown
                      content={fileContent}
                      className="w-full pb-4 h-full text-lg text-wrap break-words"
                    />
                  </div>
                ) : (
                  <div className="flex flex-col items-center justify-center h-full">
                    <p className="text-lg font-medium text-muted-foreground">
                      This file format is not supported for preview.
                    </p>
                    <Button className="mt-4" onClick={handleDownload}>
                      Download File
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
