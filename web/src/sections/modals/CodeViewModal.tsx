"use client";

import { useState, useEffect, useMemo } from "react";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";
import Modal from "@/refresh-components/Modal";
import Text from "@/refresh-components/texts/Text";
import CopyIconButton from "@/refresh-components/buttons/CopyIconButton";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import { Button } from "@opal/components";
import { SvgDownload } from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import { getCodeLanguage } from "@/lib/languages";
import MinimalMarkdown from "@/components/chat/MinimalMarkdown";
import { CodeBlock } from "@/app/app/message/CodeBlock";
import { extractCodeText } from "@/app/app/message/codeUtils";
import { fetchChatFile } from "@/lib/chat/svc";

export interface CodeViewProps {
  presentingDocument: MinimalOnyxDocument;
  onClose: () => void;
}

export default function CodeViewModal({
  presentingDocument,
  onClose,
}: CodeViewProps) {
  const [fileContent, setFileContent] = useState("");
  const [fileUrl, setFileUrl] = useState("");
  const [fileName, setFileName] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const language =
    getCodeLanguage(presentingDocument.semantic_identifier || "") ||
    "plaintext";

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

  const headerDescription = useMemo(() => {
    if (!fileContent) return "";
    return `${language} - ${lineCount} ${
      lineCount === 1 ? "line" : "lines"
    } · ${fileSize}`;
  }, [fileContent, language, lineCount, fileSize]);

  useEffect(() => {
    (async () => {
      setIsLoading(true);
      setLoadError(null);
      setFileContent("");
      const fileIdLocal =
        presentingDocument.document_id.split("__")[1] ||
        presentingDocument.document_id;

      try {
        const response = await fetchChatFile(fileIdLocal);
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        setFileUrl((prev) => {
          if (prev) {
            window.URL.revokeObjectURL(prev);
          }
          return url;
        });
        setFileName(presentingDocument.semantic_identifier || "document");
        setFileContent(await blob.text());
      } catch {
        setLoadError("Failed to load document.");
      } finally {
        setIsLoading(false);
      }
    })();
  }, [presentingDocument]);

  useEffect(() => {
    return () => {
      if (fileUrl) {
        window.URL.revokeObjectURL(fileUrl);
      }
    };
  }, [fileUrl]);

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
        height="lg"
        preventAccidentalClose={false}
        onOpenAutoFocus={(e) => e.preventDefault()}
      >
        <Modal.Header
          title={fileName || "Code"}
          description={headerDescription}
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
              <MinimalMarkdown
                content={`\`\`\`${language}\n${fileContent}\n\`\`\``}
                className="w-full h-full break-words"
                components={{
                  code: ({
                    node,
                    className: codeClassName,
                    children,
                    ...props
                  }: any) => {
                    const codeText = extractCodeText(
                      node,
                      fileContent,
                      children
                    );
                    return (
                      <CodeBlock className="" codeText={codeText}>
                        {children}
                      </CodeBlock>
                    );
                  },
                }}
              />
            )}
          </Section>
        </Modal.Body>
        <Modal.Footer>
          <Section
            flexDirection="row"
            justifyContent="between"
            alignItems="center"
          >
            <Text text03 mainContentMuted>
              {lineCount} {lineCount === 1 ? "line" : "lines"}
            </Text>
            <Section flexDirection="row" gap={0.5} width="fit">
              <CopyIconButton
                getCopyText={() => fileContent}
                tooltip="Copy code"
                size="sm"
              />
              <a
                href={fileUrl}
                download={fileName || presentingDocument.document_id}
              >
                <Button
                  icon={SvgDownload}
                  tooltip="Download"
                  size="sm"
                  prominence="tertiary"
                />
              </a>
            </Section>
          </Section>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
