"use client";

import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import * as GeneralLayouts from "@/layouts/general-layouts";
import * as TableLayouts from "@/layouts/table-layouts";
import { Card } from "@/refresh-components/cards";
import useCCPairs from "@/hooks/useCCPairs";
import { fetchHierarchyNodeSearch } from "@/lib/hierarchy/svc";
import type {
  AgentAttachedDocument,
  AgentHierarchyNode,
} from "@/lib/agents/types";
import type {
  ConnectedSource,
  HierarchyNodeSearchSummary,
} from "@/lib/hierarchy/interfaces";
import type { ProjectFile } from "@/lib/projects/types";
import type { DocumentSetSummary, ValidSources } from "@/lib/types";
import { searchDocuments } from "@/ee/lib/search/svc";
import { Disabled } from "@opal/core";
import { Switch } from "@opal/components";
import { Content, InputHorizontal } from "@opal/layouts";

import { KnowledgeAddView } from "@/sections/knowledge/agent-knowledge/KnowledgeAddView";
import { KnowledgeMainContent } from "@/sections/knowledge/agent-knowledge/KnowledgeMainContent";
import {
  KnowledgeSearchBar,
  KnowledgeSearchResultsPanel,
  KnowledgeSearchSidebar,
} from "@/sections/knowledge/agent-knowledge/KnowledgeSearch";
import { KnowledgeTwoColumnView } from "@/sections/knowledge/agent-knowledge/KnowledgeTwoColumnView";
import type {
  KnowledgeNavState,
  KnowledgeSearchResults,
  KnowledgeView,
} from "@/sections/knowledge/agent-knowledge/interfaces";

interface AgentKnowledgePaneProps {
  enableKnowledge: boolean;
  onEnableKnowledgeChange: (enabled: boolean) => void;
  selectedSources: ValidSources[];
  onSourcesChange: (sources: ValidSources[]) => void;
  documentSets: DocumentSetSummary[];
  selectedDocumentSetIds: number[];
  onDocumentSetIdsChange: (ids: number[]) => void;
  selectedDocumentIds: string[];
  onDocumentIdsChange: (ids: string[]) => void;
  selectedFolderIds: number[];
  onFolderIdsChange: (ids: number[]) => void;
  selectedFileIds: string[];
  onFileIdsChange: (ids: string[]) => void;
  allRecentFiles: ProjectFile[];
  onFileClick?: (file: ProjectFile) => void;
  onUploadChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  hasProcessingFiles: boolean;
  initialAttachedDocuments?: AgentAttachedDocument[];
  initialHierarchyNodes?: AgentHierarchyNode[];
  vectorDbEnabled?: boolean;
}

export default function AgentKnowledgePane({
  enableKnowledge,
  onEnableKnowledgeChange,
  selectedSources,
  documentSets,
  selectedDocumentSetIds,
  onDocumentSetIdsChange,
  selectedDocumentIds,
  onDocumentIdsChange,
  selectedFolderIds,
  onFolderIdsChange,
  selectedFileIds,
  onFileIdsChange,
  allRecentFiles,
  onUploadChange,
  hasProcessingFiles,
  initialAttachedDocuments,
  initialHierarchyNodes,
  vectorDbEnabled = true,
}: AgentKnowledgePaneProps) {
  const [view, setView] = useState<KnowledgeView>("main");
  const [activeSource, setActiveSource] = useState<ValidSources | undefined>();

  const [isSearchMode, setIsSearchMode] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [committedQuery, setCommittedQuery] = useState("");
  const [activeSourceFilter, setActiveSourceFilter] =
    useState<ValidSources | null>(null);
  const [searchResults, setSearchResults] =
    useState<KnowledgeSearchResults | null>(null);
  const [isSearching, setIsSearching] = useState(false);
  const [searchError, setSearchError] = useState(false);
  const searchRequestIdRef = useRef(0);
  const [searchNavigateNodeId, setSearchNavigateNodeId] = useState<
    number | undefined
  >();
  const navStateRef = useRef<KnowledgeNavState>({
    view: "add",
    activeSource: undefined,
  });

  useEffect(() => {
    if (!enableKnowledge) {
      setView("main");
      if (isSearchMode) {
        setIsSearchMode(false);
        setSearchQuery("");
        setCommittedQuery("");
        setSearchResults(null);
        setActiveSourceFilter(null);
      }
    }
  }, [enableKnowledge, isSearchMode]);

  const { ccPairs } = useCCPairs(vectorDbEnabled);
  const connectedSources: ConnectedSource[] = useMemo(() => {
    if (!ccPairs || ccPairs.length === 0) return [];
    const sourceSet = new Set<ValidSources>();
    ccPairs.forEach((pair) => sourceSet.add(pair.source));
    return Array.from(sourceSet).map((source) => ({
      source,
      connectorCount: ccPairs.filter((p) => p.source === source).length,
    }));
  }, [ccPairs]);

  const [sourceSelectionCounts, setSourceSelectionCounts] = useState<
    Map<ValidSources, number>
  >(() => {
    const counts = new Map<ValidSources, number>();

    if (initialHierarchyNodes) {
      for (const node of initialHierarchyNodes) {
        const current = counts.get(node.source) ?? 0;
        counts.set(node.source, current + 1);
      }
    }

    if (initialAttachedDocuments) {
      for (const doc of initialAttachedDocuments) {
        if (doc.source) {
          const current = counts.get(doc.source) ?? 0;
          counts.set(doc.source, current + 1);
        }
      }
    }

    return counts;
  });

  const handleSelectionCountChange = useCallback(
    (source: ValidSources, count: number) => {
      setSourceSelectionCounts((prev) => {
        const newCounts = new Map(prev);
        if (count === 0) {
          newCounts.delete(source);
        } else {
          newCounts.set(source, count);
        }
        return newCounts;
      });
    },
    []
  );

  const resultCountBySource = useMemo(() => {
    const counts = new Map<ValidSources, number>();
    if (!searchResults) return counts;
    for (const doc of searchResults.docs) {
      counts.set(doc.source_type, (counts.get(doc.source_type) ?? 0) + 1);
    }
    for (const node of searchResults.nodes) {
      counts.set(node.source, (counts.get(node.source) ?? 0) + 1);
    }
    return counts;
  }, [searchResults]);

  const hasAnyKnowledge =
    selectedDocumentSetIds.length > 0 ||
    selectedDocumentIds.length > 0 ||
    selectedFolderIds.length > 0 ||
    selectedFileIds.length > 0 ||
    selectedSources.length > 0;

  const handleNavigateToAdd = useCallback(() => setView("add"), []);
  const handleNavigateToDocumentSets = useCallback(
    () => setView("document-sets"),
    []
  );
  const handleNavigateToRecent = useCallback(() => setView("recent"), []);
  const handleNavigateToSource = useCallback((source: ValidSources) => {
    setActiveSource(source);
    setView("sources");
  }, []);

  const handleEnterSearchMode = useCallback(() => {
    if (!vectorDbEnabled) return;
    if (!isSearchMode) {
      navStateRef.current = { view, activeSource };
      setIsSearchMode(true);
      if (view === "main" || view === "add") {
        setView("add");
      }
    }
  }, [vectorDbEnabled, isSearchMode, view, activeSource]);

  const handleExitSearchMode = useCallback(() => {
    searchRequestIdRef.current++;
    setIsSearchMode(false);
    setSearchQuery("");
    setCommittedQuery("");
    setSearchResults(null);
    setSearchError(false);
    setActiveSourceFilter(null);
    setView(navStateRef.current.view);
    setActiveSource(navStateRef.current.activeSource);
  }, []);

  const runSearch = useCallback(
    async (query: string, sourceFilter: ValidSources | null) => {
      if (!query.trim() || !vectorDbEnabled) return;
      const requestId = ++searchRequestIdRef.current;
      setIsSearching(true);
      setSearchError(false);
      try {
        const [docResponse, nodeResponse] = await Promise.all([
          searchDocuments(query, {
            filters: sourceFilter ? { source_type: [sourceFilter] } : undefined,
            numHits: 30,
          }),
          fetchHierarchyNodeSearch(query, {
            sources: sourceFilter ? [sourceFilter] : undefined,
          }),
        ]);
        if (requestId !== searchRequestIdRef.current) return;
        setSearchResults({
          docs: docResponse.search_docs,
          nodes: nodeResponse.nodes,
        });
      } catch (err) {
        if (requestId !== searchRequestIdRef.current) return;
        console.error("Knowledge search failed:", err);
        setSearchResults({ docs: [], nodes: [] });
        setSearchError(true);
      } finally {
        if (requestId === searchRequestIdRef.current) {
          setIsSearching(false);
        }
      }
    },
    [vectorDbEnabled]
  );

  const handleSearchSubmit = useCallback(() => {
    if (!searchQuery.trim()) return;
    setCommittedQuery(searchQuery);
    runSearch(searchQuery, activeSourceFilter);
  }, [searchQuery, activeSourceFilter, runSearch]);

  const handleSearchClear = useCallback(() => {
    searchRequestIdRef.current++;
    setSearchQuery("");
    setCommittedQuery("");
    setSearchResults(null);
    setSearchError(false);
    setActiveSourceFilter(null);
  }, []);

  const handleSourceFilterClick = useCallback(
    (source: ValidSources | null) => {
      setActiveSourceFilter(source);
      if (committedQuery) {
        runSearch(committedQuery, source);
      }
    },
    [committedQuery, runSearch]
  );

  const handleNavigateToSearchNode = useCallback(
    (node: HierarchyNodeSearchSummary) => {
      setIsSearchMode(false);
      setSearchQuery("");
      setCommittedQuery("");
      setSearchResults(null);
      setActiveSourceFilter(null);
      setActiveSource(node.source);
      setView("sources");
      setSearchNavigateNodeId(node.id);
    },
    []
  );

  const handleDocumentSetToggle = useCallback(
    (documentSetId: number) => {
      const newIds = selectedDocumentSetIds.includes(documentSetId)
        ? selectedDocumentSetIds.filter((id) => id !== documentSetId)
        : [...selectedDocumentSetIds, documentSetId];
      onDocumentSetIdsChange(newIds);
    },
    [selectedDocumentSetIds, onDocumentSetIdsChange]
  );

  const handleFileToggle = useCallback(
    (fileId: string) => {
      const newIds = selectedFileIds.includes(fileId)
        ? selectedFileIds.filter((id) => id !== fileId)
        : [...selectedFileIds, fileId];
      onFileIdsChange(newIds);
    },
    [selectedFileIds, onFileIdsChange]
  );

  const handleDocumentToggle = useCallback(
    (documentId: string) => {
      const newIds = selectedDocumentIds.includes(documentId)
        ? selectedDocumentIds.filter((id) => id !== documentId)
        : [...selectedDocumentIds, documentId];
      onDocumentIdsChange(newIds);
    },
    [selectedDocumentIds, onDocumentIdsChange]
  );

  const handleFolderToggle = useCallback(
    (folderId: number) => {
      const newIds = selectedFolderIds.includes(folderId)
        ? selectedFolderIds.filter((id) => id !== folderId)
        : [...selectedFolderIds, folderId];
      onFolderIdsChange(newIds);
    },
    [selectedFolderIds, onFolderIdsChange]
  );

  const handleDeselectAllDocuments = useCallback(() => {
    onDocumentIdsChange([]);
  }, [onDocumentIdsChange]);

  const handleDeselectAllFolders = useCallback(() => {
    onFolderIdsChange([]);
  }, [onFolderIdsChange]);

  const renderedContent = useMemo(() => {
    switch (view) {
      case "main":
        return (
          <KnowledgeMainContent
            hasAnyKnowledge={hasAnyKnowledge}
            selectedDocumentSetIds={selectedDocumentSetIds}
            selectedDocumentIds={selectedDocumentIds}
            selectedFolderIds={selectedFolderIds}
            selectedFileIds={selectedFileIds}
            selectedSources={selectedSources}
            onAddKnowledge={handleNavigateToAdd}
            onViewEdit={handleNavigateToAdd}
          />
        );

      case "add":
        return (
          <GeneralLayouts.Section gap={0.5} alignItems="stretch" height="auto">
            {vectorDbEnabled && (
              <KnowledgeSearchBar
                query={searchQuery}
                onQueryChange={setSearchQuery}
                onSubmit={handleSearchSubmit}
                onClear={handleSearchClear}
                onBack={handleExitSearchMode}
                onFocus={handleEnterSearchMode}
                isSearchMode={isSearchMode}
              />
            )}
            {isSearchMode ? (
              <TableLayouts.TwoColumnLayout minHeight={18.75}>
                <KnowledgeSearchSidebar
                  connectedSources={connectedSources}
                  activeSourceFilter={activeSourceFilter}
                  onSourceFilterClick={handleSourceFilterClick}
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
                    onToggleDocument={handleDocumentToggle}
                    onToggleFolder={handleFolderToggle}
                    onNavigateToNode={handleNavigateToSearchNode}
                  />
                </TableLayouts.ContentColumn>
              </TableLayouts.TwoColumnLayout>
            ) : (
              <KnowledgeAddView
                connectedSources={connectedSources}
                onNavigateToDocumentSets={handleNavigateToDocumentSets}
                onNavigateToRecent={handleNavigateToRecent}
                onNavigateToSource={handleNavigateToSource}
                selectedDocumentSetIds={selectedDocumentSetIds}
                selectedFileIds={selectedFileIds}
                selectedSources={selectedSources}
                sourceSelectionCounts={sourceSelectionCounts}
                vectorDbEnabled={vectorDbEnabled}
              />
            )}
          </GeneralLayouts.Section>
        );

      case "document-sets":
      case "sources":
      case "recent":
        return (
          <KnowledgeTwoColumnView
            activeView={view}
            activeSource={activeSource}
            connectedSources={connectedSources}
            selectedSources={selectedSources}
            selectedDocumentSetIds={selectedDocumentSetIds}
            selectedFileIds={selectedFileIds}
            selectedDocumentIds={selectedDocumentIds}
            selectedFolderIds={selectedFolderIds}
            sourceSelectionCounts={sourceSelectionCounts}
            documentSets={documentSets}
            allRecentFiles={allRecentFiles}
            onNavigateToRecent={handleNavigateToRecent}
            onNavigateToDocumentSets={handleNavigateToDocumentSets}
            onNavigateToSource={handleNavigateToSource}
            onDocumentSetToggle={handleDocumentSetToggle}
            onFileToggle={handleFileToggle}
            onToggleDocument={handleDocumentToggle}
            onToggleFolder={handleFolderToggle}
            onSetDocumentIds={onDocumentIdsChange}
            onSetFolderIds={onFolderIdsChange}
            onDeselectAllDocuments={handleDeselectAllDocuments}
            onDeselectAllFolders={handleDeselectAllFolders}
            onUploadChange={onUploadChange}
            hasProcessingFiles={hasProcessingFiles}
            initialAttachedDocuments={initialAttachedDocuments}
            onSelectionCountChange={handleSelectionCountChange}
            vectorDbEnabled={vectorDbEnabled}
            isSearchMode={isSearchMode}
            searchQuery={searchQuery}
            committedQuery={committedQuery}
            activeSourceFilter={activeSourceFilter}
            searchResults={searchResults}
            isSearching={isSearching}
            searchError={searchError}
            resultCountBySource={resultCountBySource}
            onSearchQueryChange={setSearchQuery}
            onSearchSubmit={handleSearchSubmit}
            onSearchClear={handleSearchClear}
            onEnterSearchMode={handleEnterSearchMode}
            onExitSearchMode={handleExitSearchMode}
            onSourceFilterClick={handleSourceFilterClick}
            onNavigateToSearchNode={handleNavigateToSearchNode}
            searchNavigateNodeId={searchNavigateNodeId}
          />
        );

      default:
        return null;
    }
  }, [
    view,
    activeSource,
    hasAnyKnowledge,
    selectedDocumentSetIds,
    selectedDocumentIds,
    selectedFolderIds,
    selectedFileIds,
    selectedSources,
    sourceSelectionCounts,
    documentSets,
    allRecentFiles,
    connectedSources,
    hasProcessingFiles,
    initialAttachedDocuments,
    vectorDbEnabled,
    onUploadChange,
    onDocumentIdsChange,
    onFolderIdsChange,
    isSearchMode,
    searchQuery,
    committedQuery,
    activeSourceFilter,
    searchResults,
    isSearching,
    searchError,
    resultCountBySource,
    searchNavigateNodeId,
    handleNavigateToAdd,
    handleNavigateToDocumentSets,
    handleNavigateToRecent,
    handleNavigateToSource,
    handleDocumentSetToggle,
    handleFileToggle,
    handleDocumentToggle,
    handleFolderToggle,
    handleDeselectAllDocuments,
    handleDeselectAllFolders,
    handleSelectionCountChange,
    handleEnterSearchMode,
    handleExitSearchMode,
    handleSearchSubmit,
    handleSearchClear,
    handleSourceFilterClick,
    handleNavigateToSearchNode,
  ]);

  return (
    <GeneralLayouts.Section gap={0.5} alignItems="stretch" height="auto">
      <Content
        title="Knowledge"
        description="Add specific connectors and documents for this agent to use to inform its responses."
        sizePreset="main-content"
        variant="section"
      />

      <Card>
        <GeneralLayouts.Section gap={0.5} alignItems="stretch" height="auto">
          <InputHorizontal
            title="Use Knowledge"
            description="Let this agent reference these documents to inform its responses."
            withLabel
          >
            <Switch
              name="enable_knowledge"
              checked={enableKnowledge}
              onCheckedChange={onEnableKnowledgeChange}
            />
          </InputHorizontal>

          <Disabled disabled={!enableKnowledge}>
            <GeneralLayouts.Section alignItems="stretch" height="auto">
              {renderedContent}
            </GeneralLayouts.Section>
          </Disabled>
        </GeneralLayouts.Section>
      </Card>
    </GeneralLayouts.Section>
  );
}
