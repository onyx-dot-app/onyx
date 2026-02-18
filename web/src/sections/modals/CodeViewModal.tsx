"use client";

import { useState, useEffect, useCallback } from "react";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";
import MinimalMarkdown from "@/components/chat/MinimalMarkdown";
import "@/app/app/message/custom-code-styles.css";
import Modal from "@/refresh-components/Modal";
import Text from "@/refresh-components/texts/Text";
import { SvgFileText } from "@opal/icons";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import ScrollIndicatorDiv from "@/refresh-components/ScrollIndicatorDiv";
import { Section } from "@/layouts/general-layouts";
import { getCodeLanguage } from "@/lib/languages";

export interface CodeViewProps {
  presentingDocument: MinimalOnyxDocument;
  onClose: () => void;
}

export default function CodeViewModal({
  presentingDocument,
  onClose,
}: CodeViewProps) {
  const [fileContent, setFileContent] = useState("");
  const [fileName, setFileName] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const language =
    getCodeLanguage(presentingDocument.semantic_identifier || "") ||
    "plaintext";

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
        const originalFileName =
          presentingDocument.semantic_identifier || "document";
        setFileName(originalFileName);

        const text = await blob.text();
        setFileContent(text);
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
        width="md"
        height="fit"
        preventAccidentalClose={false}
        onOpenAutoFocus={(e) => e.preventDefault()}
      >
        <Modal.Header
          icon={SvgFileText}
          title={fileName || "Code"}
          onClose={onClose}
        />

        <Modal.Body padding={0} gap={0}>
          <Section padding={0} gap={0}>
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
              <ScrollIndicatorDiv
                className="flex-1 min-h-0 w-full"
                variant="shadow"
              >
                <MinimalMarkdown
                  content={`\`\`\`${language}\n${fileContent}\n\`\`\``}
                  className="w-full h-full break-words"
                />
              </ScrollIndicatorDiv>
            )}
          </Section>
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}
