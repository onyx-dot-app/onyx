"use client";

import { memo } from "react";
import * as GeneralLayouts from "@/layouts/general-layouts";
import LineItem from "@/refresh-components/buttons/LineItem";
import Text from "@/refresh-components/texts/Text";
import { getSourceMetadata } from "@/lib/sources";
import type { ConnectedSource } from "@/lib/hierarchy/interfaces";
import type { ValidSources } from "@/lib/types";
import { SvgFiles, SvgFolder } from "@opal/icons";

interface KnowledgeAddViewProps {
  connectedSources: ConnectedSource[];
  onNavigateToDocumentSets: () => void;
  onNavigateToRecent: () => void;
  onNavigateToSource: (source: ValidSources) => void;
  selectedDocumentSetIds: number[];
  selectedFileIds: string[];
  selectedSources: ValidSources[];
  sourceSelectionCounts: Map<ValidSources, number>;
  vectorDbEnabled: boolean;
}

export const KnowledgeAddView = memo(function KnowledgeAddView({
  connectedSources,
  onNavigateToDocumentSets,
  onNavigateToRecent,
  onNavigateToSource,
  selectedDocumentSetIds,
  selectedFileIds,
  selectedSources,
  sourceSelectionCounts,
  vectorDbEnabled,
}: KnowledgeAddViewProps) {
  return (
    <GeneralLayouts.Section
      gap={0.5}
      alignItems="start"
      height="auto"
      aria-label="knowledge-add-view"
    >
      <GeneralLayouts.Section
        flexDirection="row"
        justifyContent="start"
        gap={0.5}
        height="auto"
        wrap
      >
        {vectorDbEnabled && (
          <LineItem
            icon={SvgFolder}
            onClick={onNavigateToDocumentSets}
            emphasized={selectedDocumentSetIds.length > 0}
            aria-label="knowledge-add-document-sets"
            rightChildren={
              selectedDocumentSetIds.length > 0 ? (
                <Text mainUiAction className="text-action-link-05">
                  {selectedDocumentSetIds.length}
                </Text>
              ) : undefined
            }
          >
            Document Sets
          </LineItem>
        )}

        <LineItem
          icon={SvgFiles}
          description="Recent or new uploads"
          onClick={onNavigateToRecent}
          emphasized={selectedFileIds.length > 0}
          aria-label="knowledge-add-files"
          rightChildren={
            selectedFileIds.length > 0 ? (
              <Text mainUiAction className="text-action-link-05">
                {selectedFileIds.length}
              </Text>
            ) : undefined
          }
        >
          Your Files
        </LineItem>
      </GeneralLayouts.Section>

      {vectorDbEnabled && connectedSources.length > 0 && (
        <>
          <Text as="p" text03 secondaryBody>
            Connected Sources
          </Text>
          {connectedSources.map((connectedSource) => {
            const sourceMetadata = getSourceMetadata(connectedSource.source);
            const isSelected = selectedSources.includes(connectedSource.source);
            const selectionCount =
              sourceSelectionCounts.get(connectedSource.source) ?? 0;
            return (
              <LineItem
                key={connectedSource.source}
                icon={sourceMetadata.icon}
                strokeIcon={false}
                onClick={() => onNavigateToSource(connectedSource.source)}
                emphasized={isSelected || selectionCount > 0}
                aria-label={`knowledge-add-source-${connectedSource.source}`}
                rightChildren={
                  selectionCount > 0 ? (
                    <Text mainUiAction className="text-action-link-05">
                      {selectionCount}
                    </Text>
                  ) : undefined
                }
              >
                {sourceMetadata.displayName}
              </LineItem>
            );
          })}
        </>
      )}
    </GeneralLayouts.Section>
  );
});
