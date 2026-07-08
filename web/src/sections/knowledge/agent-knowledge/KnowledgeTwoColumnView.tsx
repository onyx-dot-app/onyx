"use client";

import { memo, type ChangeEvent } from "react";
import * as GeneralLayouts from "@/layouts/general-layouts";
import * as TableLayouts from "@/layouts/table-layouts";
import type { AgentAttachedDocument } from "@/lib/agents/types";
import type {
  ConnectedSource,
  HierarchyNodeSearchSummary,
} from "@/lib/hierarchy/interfaces";
import type { DocumentSetSummary, ValidSources } from "@/lib/types";
import type { ProjectFile } from "@/lib/projects/types";

import { KnowledgeSidebar } from "@/sections/knowledge/agent-knowledge/KnowledgeSidebar";
import {
  DocumentSetsTableContent,
  RecentFilesTableContent,
  SourcesTableContent,
} from "@/sections/knowledge/agent-knowledge/KnowledgeTableContent";
import {
  KnowledgeSearchBar,
  KnowledgeSearchResultsPanel,
  KnowledgeSearchSidebar,
} from "@/sections/knowledge/agent-knowledge/KnowledgeSearch";
import type {
  KnowledgeSearchResults,
  KnowledgeView,
} from "@/sections/knowledge/agent-knowledge/interfaces";

interface KnowledgeTwoColumnViewProps {
  activeView: KnowledgeView;
  activeSource?: ValidSources;
  connectedSources: ConnectedSource[];
  selectedSources: ValidSources[];
  selectedDocumentSetIds: number[];
  selectedFileIds: string[];
  selectedDocumentIds: string[];
  selectedFolderIds: number[];
  sourceSelectionCounts: Map<ValidSources, number>;
  documentSets: DocumentSetSummary[];
  allRecentFiles: ProjectFile[];
  onNavigateToRecent: () => void;
  onNavigateToDocumentSets: () => void;
  onNavigateToSource: (source: ValidSources) => void;
  onDocumentSetToggle: (id: number) => void;
  onFileToggle: (fileId: string) => void;
  onToggleDocument: (documentId: string) => void;
  onToggleFolder: (folderId: number) => void;
  onSetDocumentIds: (ids: string[]) => void;
  onSetFolderIds: (ids: number[]) => void;
  onDeselectAllDocuments: () => void;
  onDeselectAllFolders: () => void;
  onUploadChange: (e: ChangeEvent<HTMLInputElement>) => void;
  hasProcessingFiles: boolean;
  initialAttachedDocuments?: AgentAttachedDocument[];
  onSelectionCountChange: (source: ValidSources, count: number) => void;
  vectorDbEnabled: boolean;
  isSearchMode: boolean;
  searchQuery: string;
  committedQuery: string;
  activeSourceFilter: ValidSources | null;
  searchResults: KnowledgeSearchResults | null;
  isSearching: boolean;
  searchError: boolean;
  resultCountBySource: Map<ValidSources, number>;
  onSearchQueryChange: (q: string) => void;
  onSearchSubmit: () => void;
  onSearchClear: () => void;
  onEnterSearchMode: () => void;
  onExitSearchMode: () => void;
  onSourceFilterClick: (source: ValidSources | null) => void;
  onNavigateToSearchNode: (node: HierarchyNodeSearchSummary) => void;
  searchNavigateNodeId?: number;
}

export const KnowledgeTwoColumnView = memo(function KnowledgeTwoColumnView({
  activeView,
  activeSource,
  connectedSources,
  selectedSources,
  selectedDocumentSetIds,
  selectedFileIds,
  selectedDocumentIds,
  selectedFolderIds,
  sourceSelectionCounts,
  documentSets,
  allRecentFiles,
  onNavigateToRecent,
  onNavigateToDocumentSets,
  onNavigateToSource,
  onDocumentSetToggle,
  onFileToggle,
  onToggleDocument,
  onToggleFolder,
  onSetDocumentIds,
  onSetFolderIds,
  onDeselectAllDocuments,
  onDeselectAllFolders,
  onUploadChange,
  hasProcessingFiles,
  initialAttachedDocuments,
  onSelectionCountChange,
  vectorDbEnabled,
  isSearchMode,
  searchQuery,
  committedQuery,
  activeSourceFilter,
  searchResults,
  isSearching,
  searchError,
  resultCountBySource,
  onSearchQueryChange,
  onSearchSubmit,
  onSearchClear,
  onEnterSearchMode,
  onExitSearchMode,
  onSourceFilterClick,
  onNavigateToSearchNode,
  searchNavigateNodeId,
}: KnowledgeTwoColumnViewProps) {
  return (
    <GeneralLayouts.Section gap={0.5} alignItems="stretch" height="auto">
      {vectorDbEnabled && (
        <KnowledgeSearchBar
          query={searchQuery}
          onQueryChange={onSearchQueryChange}
          onSubmit={onSearchSubmit}
          onClear={onSearchClear}
          onBack={onExitSearchMode}
          onFocus={onEnterSearchMode}
          isSearchMode={isSearchMode}
        />
      )}

      {isSearchMode ? (
        <TableLayouts.TwoColumnLayout minHeight={18.75}>
          <KnowledgeSearchSidebar
            connectedSources={connectedSources}
            activeSourceFilter={activeSourceFilter}
            onSourceFilterClick={onSourceFilterClick}
            resultCountBySource={resultCountBySource}
            vectorDbEnabled={vectorDbEnabled}
          />
          <TableLayouts.ContentColumn>
            <KnowledgeSearchResultsPanel
              committedQuery={committedQuery}
              searchQuery={searchQuery}
              isSearching={isSearching}
              searchError={searchError}
              results={searchResults}
              activeSourceFilter={activeSourceFilter}
              selectedDocumentIds={selectedDocumentIds}
              selectedFolderIds={selectedFolderIds}
              onToggleDocument={onToggleDocument}
              onToggleFolder={onToggleFolder}
              onNavigateToNode={onNavigateToSearchNode}
            />
          </TableLayouts.ContentColumn>
        </TableLayouts.TwoColumnLayout>
      ) : (
        <TableLayouts.TwoColumnLayout minHeight={18.75}>
          <KnowledgeSidebar
            activeView={activeView}
            activeSource={activeSource}
            connectedSources={connectedSources}
            selectedSources={selectedSources}
            selectedDocumentSetIds={selectedDocumentSetIds}
            selectedFileIds={selectedFileIds}
            sourceSelectionCounts={sourceSelectionCounts}
            onNavigateToRecent={onNavigateToRecent}
            onNavigateToDocumentSets={onNavigateToDocumentSets}
            onNavigateToSource={onNavigateToSource}
            vectorDbEnabled={vectorDbEnabled}
          />

          <TableLayouts.ContentColumn>
            {activeView === "document-sets" && (
              <DocumentSetsTableContent
                documentSets={documentSets}
                selectedDocumentSetIds={selectedDocumentSetIds}
                onDocumentSetToggle={onDocumentSetToggle}
              />
            )}
            {activeView === "sources" && activeSource && (
              <SourcesTableContent
                source={activeSource}
                selectedDocumentIds={selectedDocumentIds}
                onToggleDocument={onToggleDocument}
                onSetDocumentIds={onSetDocumentIds}
                selectedFolderIds={selectedFolderIds}
                onToggleFolder={onToggleFolder}
                onSetFolderIds={onSetFolderIds}
                onDeselectAllDocuments={onDeselectAllDocuments}
                onDeselectAllFolders={onDeselectAllFolders}
                initialAttachedDocuments={initialAttachedDocuments}
                onSelectionCountChange={onSelectionCountChange}
                initialNodeId={searchNavigateNodeId}
              />
            )}
            {activeView === "recent" && (
              <RecentFilesTableContent
                allRecentFiles={allRecentFiles}
                selectedFileIds={selectedFileIds}
                onToggleFile={onFileToggle}
                onUploadChange={onUploadChange}
                hasProcessingFiles={hasProcessingFiles}
              />
            )}
          </TableLayouts.ContentColumn>
        </TableLayouts.TwoColumnLayout>
      )}
    </GeneralLayouts.Section>
  );
});
