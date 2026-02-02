"use client";

import { useState, useEffect } from "react";
import Modal from "@/refresh-components/Modal";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import { SvgFileText, SvgDownloadCloud, SvgImage } from "@opal/icons";
import { getArtifactUrl, FileSystemEntry } from "@/lib/build/client";

interface FilePreviewModalProps {
  sessionId: string;
  entry: FileSystemEntry;
  onClose: () => void;
}

export default function FilePreviewModal({
  sessionId,
  entry,
  onClose,
}: FilePreviewModalProps) {
  const [content, setContent] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const downloadUrl = getArtifactUrl(sessionId, entry.path);
  const isImage = entry.mime_type?.startsWith("image/");

  useEffect(() => {
    if (isImage) {
      setIsLoading(false);
      return;
    }

    const fetchContent = async () => {
      setIsLoading(true);
      setError(null);
      try {
        const response = await fetch(downloadUrl);
        if (!response.ok) {
          throw new Error(`Failed to fetch file: ${response.statusText}`);
        }
        const text = await response.text();
        setContent(text);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load file");
      } finally {
        setIsLoading(false);
      }
    };

    fetchContent();
  }, [downloadUrl, isImage]);

  return (
    <Modal open onOpenChange={(open) => !open && onClose()}>
      <Modal.Content>
        <Modal.Header
          icon={isImage ? SvgImage : SvgFileText}
          title={entry.name}
          description={entry.path}
          onClose={onClose}
        />
        <Modal.Body>
          {isLoading ? (
            <div className="flex items-center justify-center p-8">
              <SimpleLoader />
            </div>
          ) : error ? (
            <Text secondaryBody className="text-status-error-01">
              {error}
            </Text>
          ) : isImage ? (
            <div className="flex items-center justify-center p-4">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={downloadUrl}
                alt={entry.name}
                className="max-w-full max-h-[60vh] object-contain rounded-08"
              />
            </div>
          ) : (
            <div className="w-full overflow-auto max-h-[60vh] rounded-08 bg-background-neutral-02 border border-border-01">
              <pre className="p-4 text-sm font-mono whitespace-pre-wrap break-words text-text-04">
                {content}
              </pre>
            </div>
          )}
        </Modal.Body>
        <Modal.Footer>
          <a href={downloadUrl} download={entry.name}>
            <Button action secondary leftIcon={SvgDownloadCloud}>
              Download
            </Button>
          </a>
          <Button action primary onClick={onClose}>
            Close
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
