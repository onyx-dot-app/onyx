"use client";

import { useState, useEffect, useCallback } from "react";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
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
  const [renderCount, setRenderCount] = useState(0);

  // Log render count on each render
  useEffect(() => {
    setRenderCount((prevCount) => prevCount + 1);
    console.log(`TextView component rendered ${renderCount + 1} times`);
  }, []);

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

  const fetchFile = useCallback(async () => {
    console.log("fetching file");
    setIsLoading(true);
    const fileIdLocal =
      presentingDocument.document_id.split("__")[1] ||
      presentingDocument.document_id;

    try {
      const response = await fetch(
        `/api/chat/file/${encodeURIComponent(fileIdLocal)}`,
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
      console.error("Error fetching file:", error);
    } finally {
      // Keep the slight delay for a smoother loading experience
      setTimeout(() => {
        setIsLoading(false);
        console.log("finished loading");
      }, 1000);
    }
  }, [presentingDocument]);

  useEffect(() => {
    fetchFile();
  }, []);

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
        overlayClassName="z-[3000]"
        className="z-[3001] max-w-4xl w-[90vw] flex flex-col justify-between gap-y-0 h-[90vh] max-h-[90vh] p-0"
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
            <Button variant="ghost" size="icon" onClick={onClose}>
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
                    title="File Viewer"
                  />
                ) : isMarkdownFormat(fileType) ? (
                  <div className="w-full h-full p-6 overflow-y-scroll overflow-x-hidden">
                    {fileType.startsWith("text/csv") ? (
                      (() => {
                        const lines = fileContent
                          .split(/\r?\n/)
                          .filter((l) => l.length > 0);
                        const headers =
                          lines.length > 0 ? lines[0]?.split(",") : [];
                        const rows = lines
                          .slice(1)
                          .map((line) => line.split(","));
                        return (
                          <div className="w-full h-full overflow-auto">
                            <Table>
                              <TableHeader>
                                <TableRow>
                                  {headers?.map((h, i) => (
                                    <TableHead key={i}>{h}</TableHead>
                                  ))}
                                </TableRow>
                              </TableHeader>
                              <TableBody>
                                {rows.map((row, rIdx) => (
                                  <TableRow key={rIdx}>
                                    {headers?.map((_, cIdx) => (
                                      <TableCell key={cIdx}>
                                        {row?.[cIdx] ?? ""}
                                      </TableCell>
                                    ))}
                                  </TableRow>
                                ))}
                              </TableBody>
                            </Table>
                          </div>
                        );
                      })()
                    ) : (
                      <MinimalMarkdown
                        content={fileContent}
                        className="w-full pb-4 h-full text-lg break-words"
                      />
                    )}
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
