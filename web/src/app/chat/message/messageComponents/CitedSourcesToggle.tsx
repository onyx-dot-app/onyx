import React from "react";
import { FiFileText } from "react-icons/fi";
import { SourceIcon } from "@/components/SourceIcon";
import { WebResultIcon } from "@/components/WebResultIcon";
import { OnyxDocument } from "@/lib/search/interfaces";
import { ValidSources } from "@/lib/types";
import { IconProps } from "@/components/icons/icons";
import Tag from "@/refresh-components/buttons/Tag";

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

  // Get unique icon factory functions
  const getIconFactories = (): React.FunctionComponent<IconProps>[] => {
    const seenSources = new Set<string>();
    const factories: React.FunctionComponent<IconProps>[] = [];

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
      if (factories.length >= 2) break;

      let sourceKey: string;
      let iconFactory: React.FunctionComponent<IconProps>;

      if (doc) {
        if (doc.is_internet || doc.source_type === ValidSources.Web) {
          // For web sources, use the hostname as the unique key
          try {
            const hostname = new URL(doc.link).hostname;
            sourceKey = `web_${hostname}`;
          } catch {
            sourceKey = `web_${doc.link}`;
          }
          const url = doc.link;
          iconFactory = (props: IconProps) => (
            <WebResultIcon url={url} size={props.size} />
          );
        } else {
          sourceKey = `source_${doc.source_type}`;
          const sourceType = doc.source_type;
          iconFactory = (props: IconProps) => (
            <SourceIcon sourceType={sourceType} iconSize={props.size ?? 10} />
          );
        }
      } else {
        // Fallback for missing document (only possible with citations)
        sourceKey = `file_${documentId}`;
        iconFactory = (props: IconProps) => (
          <FiFileText size={props.size} className={props.className} />
        );
      }

      if (!seenSources.has(sourceKey)) {
        seenSources.add(sourceKey);
        factories.push(iconFactory);
      }
    }

    return factories;
  };

  return (
    <Tag label="Sources" onClick={() => onToggle(nodeId)}>
      {getIconFactories()}
    </Tag>
  );
}
