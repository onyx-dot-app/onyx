"use client";

import React, { useState, useEffect, useCallback } from "react";
import Button from "@/refresh-components/buttons/Button";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";
import { Button as OpalButton } from "@opal/components";
import Modal, { BasicModalFooter } from "@/refresh-components/Modal";
import Text from "@/refresh-components/texts/Text";
import { SvgDownloadCloud, SvgFileText } from "@opal/icons";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import { Section } from "@/layouts/general-layouts";

export interface DocumentData {
  fileContent: string;
  fileUrl: string;
  fileName: string;
  fileType: string;
  handleDownload: () => void;
}

export interface DocumentViewModalProps {
  presentingDocument: MinimalOnyxDocument;
  onClose: () => void;
  headerExtras?: (data: DocumentData) => React.ReactNode;
  renderContent: (data: DocumentData) => React.ReactNode;
  width?: "sm" | "md" | "lg";
}

function isTextBasedMimeType(mimeType: string): boolean {
  return mimeType.startsWith("text/");
}

export default function DocumentViewModal({
  presentingDocument,
  onClose,
  headerExtras,
  renderContent,
  width = "lg",
}: DocumentViewModalProps) {
  const [fileContent, setFileContent] = useState("");
  const [fileUrl, setFileUrl] = useState("");
  const [fileName, setFileName] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [fileType, setFileType] = useState("application/octet-stream");

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

        // Read text content for text-based MIME types or if the caller will need it
        if (
          isTextBasedMimeType(contentType) ||
          contentType === "application/octet-stream"
        ) {
          const text = await blob.text();
          setFileContent(text);
        }
      } catch (error) {
        if (signal?.aborted) {
          return;
        }
        setLoadError("Failed to load document.");
      } finally {
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

  const data: DocumentData = {
    fileContent,
    fileUrl,
    fileName,
    fileType,
    handleDownload,
  };

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
        width={width}
        height="full"
        preventAccidentalClose={false}
        onOpenAutoFocus={(e) => e.preventDefault()}
      >
        <Modal.Header
          icon={SvgFileText}
          title={fileName || "Document"}
          onClose={onClose}
        >
          <Section flexDirection="row" justifyContent="start" gap={0.25}>
            {headerExtras?.(data)}
            <OpalButton
              prominence="tertiary"
              onClick={handleDownload}
              icon={SvgDownloadCloud}
              tooltip="Download"
            />
          </Section>
        </Modal.Header>

        <Modal.Body>
          <Section>
            {isLoading ? (
              <SimpleLoader className="h-8 w-8" />
            ) : loadError ? (
              <Text text03 mainUiBody>
                {loadError}
              </Text>
            ) : (
              renderContent(data)
            )}
          </Section>
        </Modal.Body>

        <Modal.Footer>
          <BasicModalFooter
            submit={<Button onClick={handleDownload}>Download File</Button>}
          />
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
