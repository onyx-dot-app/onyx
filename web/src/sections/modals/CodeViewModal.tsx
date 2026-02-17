"use client";

import { MinimalOnyxDocument } from "@/lib/search/interfaces";
import DocumentViewModal, {
  DocumentData,
} from "@/sections/modals/DocumentViewModal";
import { getCodeLanguage } from "@/lib/languages";
import MinimalMarkdown from "@/components/chat/MinimalMarkdown";
import "@/app/app/message/custom-code-styles.css";
import ScrollIndicatorDiv from "@/refresh-components/ScrollIndicatorDiv";

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
    <ScrollIndicatorDiv className="flex-1 min-h-0 p-4" variant="shadow">
      <MinimalMarkdown
        content={`\`\`\`${language}\n${data.fileContent}\n\`\`\``}
        className="w-full pb-4 h-full break-words"
      />
    </ScrollIndicatorDiv>
  );

  return (
    <DocumentViewModal
      presentingDocument={presentingDocument}
      onClose={onClose}
      renderContent={renderContent}
    />
  );
}
