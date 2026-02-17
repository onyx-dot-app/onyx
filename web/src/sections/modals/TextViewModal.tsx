"use client";

import { useState } from "react";
import Button from "@/refresh-components/buttons/Button";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";
import { Button as OpalButton } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import { SvgZoomIn, SvgZoomOut } from "@opal/icons";
import DocumentViewModal, {
  DocumentData,
} from "@/sections/modals/DocumentViewModal";
import TextViewContent from "@/sections/modals/TextViewContent";

export interface TextViewProps {
  presentingDocument: MinimalOnyxDocument;
  onClose: () => void;
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
    const { fileType, fileUrl, fileName, fileContent, handleDownload } = data;

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
