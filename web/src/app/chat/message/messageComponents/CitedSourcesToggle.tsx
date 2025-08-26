import React from "react";
import { FiFileText } from "react-icons/fi";
import { SourceIcon } from "@/components/SourceIcon";
import { WebResultIcon } from "@/components/WebResultIcon";
import { OnyxDocument } from "@/lib/search/interfaces";
import { ValidSources } from "@/lib/types";

interface SourcesToggleProps {
  citations: Array<{
    citation_num: number;
    document_id: string;
  }>;
  documentMap: Map<string, OnyxDocument>;
  messageId: number;
  onToggle: (messageId: number) => void;
}

export const CitedSourcesToggle = ({
  citations,
  documentMap,
  messageId,
  onToggle,
}: SourcesToggleProps) => {
  // If no citations but we have documents, use the first 2 documents as fallback
  const hasContent = citations.length > 0 || documentMap.size > 0;
  if (!hasContent) {
    return null;
  }

  // Helper function to create icon for a document
  const createDocumentIcon = (doc: OnyxDocument, documentId: string) => {
    let sourceKey: string;
    let iconElement: React.ReactNode;

    if (doc.is_internet || doc.source_type === ValidSources.Web) {
      // For web sources, use the hostname as the unique key
      try {
        const hostname = new URL(doc.link).hostname;
        sourceKey = `web_${hostname}`;
      } catch {
        sourceKey = `web_${doc.link}`;
      }
      iconElement = <WebResultIcon key={documentId} url={doc.link} size={16} />;
    } else {
      sourceKey = `source_${doc.source_type}`;
      iconElement = (
        <SourceIcon
          key={documentId}
          sourceType={doc.source_type}
          iconSize={16}
        />
      );
    }

    return { sourceKey, iconElement };
  };

  // Get unique icons by creating a unique identifier for each source
  const getUniqueIcons = () => {
    const seenSources = new Set<string>();
    const uniqueIcons: Array<{
      id: string;
      element: React.ReactNode;
    }> = [];

    // Get documents to process - either from citations or fallback to all documents
    const documentsToProcess =
      citations.length > 0
        ? citations.map((citation) => ({
            documentId: citation.document_id,
            doc: documentMap.get(citation.document_id),
          }))
        : Array.from(documentMap.entries()).map(([documentId, doc]) => ({
            documentId,
            doc,
          }));

    for (const { documentId, doc } of documentsToProcess) {
      if (uniqueIcons.length >= 2) break;

      let sourceKey: string;
      let iconElement: React.ReactNode;

      if (doc) {
        const iconData = createDocumentIcon(doc, documentId);
        sourceKey = iconData.sourceKey;
        iconElement = iconData.iconElement;
      } else {
        // Fallback for missing document (only possible with citations)
        sourceKey = `file_${documentId}`;
        iconElement = <FiFileText key={documentId} size={16} />;
      }

      if (!seenSources.has(sourceKey)) {
        seenSources.add(sourceKey);
        uniqueIcons.push({
          id: sourceKey,
          element: iconElement,
        });
      }
    }

    return uniqueIcons;
  };

  const uniqueIcons = getUniqueIcons();

  return (
    <div
      className="
        hover:bg-background-chat-hover 
        text-text-600 
        p-1.5 
        rounded 
        h-fit 
        cursor-pointer 
        flex 
        items-center 
        gap-1
      "
      onClick={() => onToggle(messageId)}
    >
      <div className="flex items-center">
        {uniqueIcons.map((icon, index) => (
          <div key={icon.id}>{icon.element}</div>
        ))}
        {/* Show count for remaining items */}
        {(() => {
          const totalCount =
            citations.length > 0 ? citations.length : documentMap.size;
          const remainingCount = totalCount - uniqueIcons.length;
          return remainingCount > 0 ? (
            <span className="text-xs text-text-500 ml-1">
              +{remainingCount}
            </span>
          ) : null;
        })()}
      </div>
      <span className="text-sm text-text-700">Sources</span>
    </div>
  );
};
