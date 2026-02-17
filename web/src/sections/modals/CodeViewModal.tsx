"use client";

import { MinimalOnyxDocument } from "@/lib/search/interfaces";
import DocumentViewModal, {
  DocumentData,
} from "@/sections/modals/DocumentViewModal";
import CodeViewContent, {
  getCodeLanguage,
} from "@/sections/modals/CodeViewContent";

export interface CodeViewProps {
  presentingDocument: MinimalOnyxDocument;
  onClose: () => void;
}

export default function CodeViewModal({
  presentingDocument,
  onClose,
}: CodeViewProps) {
  const language =
    getCodeLanguage(presentingDocument.semantic_identifier || "") ||
    "plaintext";

  const renderContent = (data: DocumentData) => (
    <CodeViewContent fileContent={data.fileContent} language={language} />
  );

  return (
    <DocumentViewModal
      presentingDocument={presentingDocument}
      onClose={onClose}
      renderContent={renderContent}
    />
  );
}
