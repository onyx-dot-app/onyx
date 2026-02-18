"use client";

import { useState, useMemo } from "react";
import Button from "@/refresh-components/buttons/Button";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";
import { Button as OpalButton } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import { SvgZoomIn, SvgZoomOut } from "@opal/icons";
import DocumentViewModal, {
  DocumentData,
} from "@/sections/modals/DocumentViewModal";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import MinimalMarkdown from "@/components/chat/MinimalMarkdown";
import ScrollIndicatorDiv from "@/refresh-components/ScrollIndicatorDiv";
import { cn } from "@/lib/utils";

export interface TextViewProps {
  presentingDocument: MinimalOnyxDocument;
  onClose: () => void;
}

/**
 * Resolves an effective content type by overriding generic octet-stream
 * when the file name suggests a known text-based extension.
 */
function resolveTextContentType(
  rawContentType: string,
  fileName: string
): string {
  if (rawContentType !== "application/octet-stream") return rawContentType;
  const lowerName = fileName.toLowerCase();
  if (lowerName.endsWith(".md") || lowerName.endsWith(".markdown"))
    return "text/markdown";
  if (lowerName.endsWith(".txt")) return "text/plain";
  if (lowerName.endsWith(".csv")) return "text/csv";
  return rawContentType;
}

function isMarkdownFormat(mimeType: string): boolean {
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
}

function isImageFormat(mimeType: string): boolean {
  const imageFormats = [
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/svg+xml",
  ];
  return imageFormats.some((format) => mimeType.startsWith(format));
}

function isSupportedIframeFormat(mimeType: string): boolean {
  const supportedFormats = [
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/svg+xml",
  ];
  return supportedFormats.some((format) => mimeType.startsWith(format));
}

function TextViewContent({
  fileContent,
  fileType,
}: {
  fileContent: string;
  fileType: string;
}) {
  const csvData = useMemo(() => {
    if (!fileType.startsWith("text/csv")) {
      return null;
    }

    const lines = fileContent.split(/\r?\n/).filter((l) => l.length > 0);
    const headers = lines.length > 0 ? lines[0]?.split(",") ?? [] : [];
    const rows = lines.slice(1).map((line) => line.split(","));

    return { headers, rows } as { headers: string[]; rows: string[][] };
  }, [fileContent, fileType]);

  return (
    <ScrollIndicatorDiv className="flex-1 min-h-0 p-4" variant="shadow">
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
                      cIdx === 0 && "sticky left-0 bg-background-tint-01",
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
  );
}

export default function TextViewModal({
  presentingDocument,
  onClose,
}: TextViewProps) {
  const [zoom, setZoom] = useState(100);

  const handleZoomIn = () => setZoom((prev) => Math.min(prev + 25, 200));
  const handleZoomOut = () => setZoom((prev) => Math.max(prev - 25, 100));

  const renderHeaderExtras = () => (
    <>
      <OpalButton
        prominence="tertiary"
        onClick={handleZoomOut}
        icon={SvgZoomOut}
        tooltip="Zoom Out"
      />
      <Text mainUiBody>{zoom}%</Text>
      <OpalButton
        prominence="tertiary"
        onClick={handleZoomIn}
        icon={SvgZoomIn}
        tooltip="Zoom In"
      />
    </>
  );

  const renderContent = (data: DocumentData) => {
    const { fileUrl, fileName, fileContent, handleDownload } = data;
    const fileType = resolveTextContentType(data.fileType, fileName);

    return (
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
          <TextViewContent fileContent={fileContent} fileType={fileType} />
        ) : (
          <div className="flex flex-col items-center justify-center flex-1 min-h-0 p-6 gap-4">
            <Text as="p" text03 mainUiBody>
              This file format is not supported for preview.
            </Text>
            <Button onClick={handleDownload}>Download File</Button>
          </div>
        )}
      </div>
    );
  };

  return (
    <DocumentViewModal
      presentingDocument={presentingDocument}
      onClose={onClose}
      headerExtras={renderHeaderExtras}
      renderContent={renderContent}
    />
  );
}
