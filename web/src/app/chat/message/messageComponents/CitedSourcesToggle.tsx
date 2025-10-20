import React from "react";
import { FiFileText } from "react-icons/fi";
import { SourceIcon } from "@/components/SourceIcon";
import { WebResultIcon } from "@/components/WebResultIcon";
import { OnyxDocument } from "@/lib/search/interfaces";
import { ValidSources } from "@/lib/types";
import Tag from "@/refresh-components/buttons/Tag";

const SIZE = 14;

interface SourcesToggleProps {
  citations: Array<{
    citation_num: number;
    document_id: string;
  }>;
  documentMap: Map<string, OnyxDocument>;
  nodeId: number;
  onToggle: (toggledNodeId: number) => void;
}

export default function CitedSourcesToggle({
  citations,
  documentMap,
  nodeId,
  onToggle,
}: SourcesToggleProps) {
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
      iconElement = (
        <WebResultIcon key={documentId} url={doc.link} size={SIZE} />
      );
    } else {
      sourceKey = `source_${doc.source_type}`;
      iconElement = (
        <SourceIcon
          key={documentId}
          sourceType={doc.source_type}
          iconSize={SIZE}
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
        iconElement = <FiFileText key={documentId} size={SIZE} />;
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
    <Tag label="Sources" onClick={() => onToggle(nodeId)}>
      {uniqueIcons.map((icon) => (() => icon.element) as any)}
    </Tag>
  );
}
