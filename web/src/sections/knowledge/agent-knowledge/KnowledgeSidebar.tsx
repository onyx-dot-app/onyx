"use client";

import * as TableLayouts from "@/layouts/table-layouts";
import LineItem from "@/refresh-components/buttons/LineItem";
import Text from "@/refresh-components/texts/Text";
import { getSourceMetadata } from "@/lib/sources";
import type { ConnectedSource } from "@/lib/hierarchy/interfaces";
import type { ValidSources } from "@/lib/types";
import { Divider } from "@opal/components";
import { SvgFiles, SvgFolder } from "@opal/icons";

import type { KnowledgeView } from "@/sections/knowledge/agent-knowledge/interfaces";

interface KnowledgeSidebarProps {
  activeView: KnowledgeView;
  activeSource?: ValidSources;
  connectedSources: ConnectedSource[];
  selectedSources: ValidSources[];
  selectedDocumentSetIds: number[];
  selectedFileIds: string[];
  sourceSelectionCounts: Map<ValidSources, number>;
  onNavigateToRecent: () => void;
  onNavigateToDocumentSets: () => void;
  onNavigateToSource: (source: ValidSources) => void;
  vectorDbEnabled: boolean;
}

export function KnowledgeSidebar({
  activeView,
  activeSource,
  connectedSources,
  selectedSources,
  selectedDocumentSetIds,
  selectedFileIds,
  sourceSelectionCounts,
  onNavigateToRecent,
  onNavigateToDocumentSets,
  onNavigateToSource,
  vectorDbEnabled,
}: KnowledgeSidebarProps) {
  return (
    <TableLayouts.SidebarLayout aria-label="knowledge-sidebar">
      <LineItem
        icon={SvgFiles}
        onClick={onNavigateToRecent}
        selected={activeView === "recent"}
        emphasized={activeView === "recent" || selectedFileIds.length > 0}
        aria-label="knowledge-sidebar-files"
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

      {vectorDbEnabled && (
        <>
          <LineItem
            icon={SvgFolder}
            onClick={onNavigateToDocumentSets}
            selected={activeView === "document-sets"}
            emphasized={
              activeView === "document-sets" ||
              selectedDocumentSetIds.length > 0
            }
            aria-label="knowledge-sidebar-document-sets"
            rightChildren={
              selectedDocumentSetIds.length > 0 ? (
                <Text mainUiAction className="text-action-link-05">
                  {selectedDocumentSetIds.length}
                </Text>
              ) : undefined
            }
          >
            Document Set
          </LineItem>

          <Divider paddingParallel="fit" paddingPerpendicular="fit" />

          {connectedSources.map((connectedSource) => {
            const sourceMetadata = getSourceMetadata(connectedSource.source);
            const isSelected = selectedSources.includes(connectedSource.source);
            const isActive =
              activeView === "sources" &&
              activeSource === connectedSource.source;
            const selectionCount =
              sourceSelectionCounts.get(connectedSource.source) ?? 0;

            return (
              <LineItem
                key={connectedSource.source}
                icon={sourceMetadata.icon}
                strokeIcon={false}
                onClick={() => onNavigateToSource(connectedSource.source)}
                selected={isActive}
                emphasized={isActive || isSelected || selectionCount > 0}
                aria-label={`knowledge-sidebar-source-${connectedSource.source}`}
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
    </TableLayouts.SidebarLayout>
  );
}
