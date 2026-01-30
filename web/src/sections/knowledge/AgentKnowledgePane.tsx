"use client";

import React, { useState, useMemo, useCallback, memo } from "react";
import * as GeneralLayouts from "@/layouts/general-layouts";
import * as TableLayouts from "@/layouts/table-layouts";
import * as InputLayouts from "@/layouts/input-layouts";
import { Card } from "@/refresh-components/cards";
import Button from "@/refresh-components/buttons/Button";
import IconButton from "@/refresh-components/buttons/IconButton";
import Text from "@/refresh-components/texts/Text";
import Truncated from "@/refresh-components/texts/Truncated";
import LineItem from "@/refresh-components/buttons/LineItem";
import Separator from "@/refresh-components/Separator";
import Switch from "@/refresh-components/inputs/Switch";
import Checkbox from "@/refresh-components/inputs/Checkbox";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import {
  SvgPlusCircle,
  SvgArrowUpRight,
  SvgFiles,
  SvgFolder,
} from "@opal/icons";
import type { CCPairSummary } from "@/lib/types";
import { getSourceMetadata } from "@/lib/sources";
import { ValidSources, DocumentSetSummary } from "@/lib/types";
import useCCPairs from "@/hooks/useCCPairs";
import { ConnectedSource } from "@/lib/hierarchy/types";
import { ProjectFile } from "@/app/app/projects/projectsService";
import { timeAgo } from "@/lib/time";
import Spacer from "@/refresh-components/Spacer";

// Knowledge pane view states
type KnowledgeView = "main" | "add" | "document-sets" | "sources" | "recent";

// ============================================================================
// KNOWLEDGE SIDEBAR - Left column showing all knowledge categories
// ============================================================================

interface KnowledgeSidebarProps {
  activeView: KnowledgeView;
  activeSource?: ValidSources;
  connectedSources: ConnectedSource[];
  selectedSources: ValidSources[];
  selectedDocumentSetIds: number[];
  selectedFileIds: string[];
  onNavigateToRecent: () => void;
  onNavigateToDocumentSets: () => void;
  onNavigateToSource: (source: ValidSources) => void;
}

function KnowledgeSidebar({
  activeView,
  activeSource,
  connectedSources,
  selectedSources,
  selectedDocumentSetIds,
  selectedFileIds,
  onNavigateToRecent,
  onNavigateToDocumentSets,
  onNavigateToSource,
}: KnowledgeSidebarProps) {
  return (
    <TableLayouts.SidebarLayout aria-label="knowledge-sidebar">
      <LineItem
        icon={SvgFiles}
        onClick={onNavigateToRecent}
        selected={activeView === "recent"}
        emphasized={activeView === "recent" || selectedFileIds.length > 0}
        aria-label="knowledge-sidebar-files"
      >
        Your Files
      </LineItem>

      <LineItem
        icon={SvgFolder}
        description="(deprecated)"
        onClick={onNavigateToDocumentSets}
        selected={activeView === "document-sets"}
        emphasized={
          activeView === "document-sets" || selectedDocumentSetIds.length > 0
        }
        aria-label="knowledge-sidebar-document-sets"
      >
        Document Set
      </LineItem>

      <Separator noPadding />

      {connectedSources.map((connectedSource) => {
        const sourceMetadata = getSourceMetadata(connectedSource.source);
        const isSelected = selectedSources.includes(connectedSource.source);
        const isActive =
          activeView === "sources" && activeSource === connectedSource.source;

        return (
          <LineItem
            key={connectedSource.source}
            icon={sourceMetadata.icon}
            onClick={() => onNavigateToSource(connectedSource.source)}
            selected={isActive}
            emphasized={isActive || isSelected}
            aria-label={`knowledge-sidebar-source-${connectedSource.source}`}
          >
            {sourceMetadata.displayName}
          </LineItem>
        );
      })}
    </TableLayouts.SidebarLayout>
  );
}

// ============================================================================
// KNOWLEDGE TABLE - Generic table component for knowledge items
// ============================================================================

interface KnowledgeTableColumn<T> {
  key: string;
  header: string;
  sortable?: boolean;
  width?: number; // Width in rem
  render: (item: T) => React.ReactNode;
}

interface KnowledgeTableProps<T> {
  items: T[];
  columns: KnowledgeTableColumn<T>[];
  getItemId: (item: T) => string | number;
  selectedIds: (string | number)[];
  onToggleItem: (id: string | number) => void;
  searchValue?: string;
  onSearchChange?: (value: string) => void;
  searchPlaceholder?: string;
  headerActions?: React.ReactNode;
  emptyMessage?: string;
}

function KnowledgeTable<T>({
  items,
  columns,
  getItemId,
  selectedIds,
  onToggleItem,
  searchValue,
  onSearchChange,
  searchPlaceholder = "Search...",
  headerActions,
  emptyMessage = "No items available.",
  ariaLabelPrefix,
}: KnowledgeTableProps<T> & { ariaLabelPrefix?: string }) {
  return (
    <GeneralLayouts.Section gap={0} alignItems="stretch" justifyContent="start">
      {/* Header with search and actions */}
      <GeneralLayouts.Section
        flexDirection="row"
        justifyContent="start"
        alignItems="center"
        gap={0.5}
        height="auto"
      >
        {onSearchChange !== undefined && (
          <GeneralLayouts.Section height="auto">
            <InputTypeIn
              leftSearchIcon
              value={searchValue ?? ""}
              onChange={(e) => onSearchChange?.(e.target.value)}
              placeholder={searchPlaceholder}
              variant="internal"
            />
          </GeneralLayouts.Section>
        )}
        {headerActions}
      </GeneralLayouts.Section>

      <Spacer rem={0.5} />

      {/* Table header */}
      <TableLayouts.TableRow>
        <TableLayouts.CheckboxCell />
        {columns.map((column) => (
          <TableLayouts.TableCell
            key={column.key}
            flex={!column.width}
            width={column.width}
          >
            <GeneralLayouts.Section
              flexDirection="row"
              justifyContent="start"
              alignItems="center"
              gap={0.25}
              height="auto"
            >
              <Text secondaryBody text03>
                {column.header}
              </Text>
            </GeneralLayouts.Section>
          </TableLayouts.TableCell>
        ))}
      </TableLayouts.TableRow>

      <Separator noPadding />

      {/* Table body */}
      {items.length === 0 ? (
        <GeneralLayouts.Section height="auto" padding={1}>
          <Text text03 secondaryBody>
            {emptyMessage}
          </Text>
        </GeneralLayouts.Section>
      ) : (
        <GeneralLayouts.Section gap={0} alignItems="stretch" height="auto">
          {items.map((item) => {
            const id = getItemId(item);
            const isSelected = selectedIds.includes(id);

            return (
              <TableLayouts.TableRow
                key={String(id)}
                selected={isSelected}
                onClick={() => onToggleItem(id)}
                aria-label={
                  ariaLabelPrefix ? `${ariaLabelPrefix}-${id}` : undefined
                }
              >
                <TableLayouts.CheckboxCell>
                  <Checkbox
                    checked={isSelected}
                    onCheckedChange={() => onToggleItem(id)}
                  />
                </TableLayouts.CheckboxCell>
                {columns.map((column) => (
                  <TableLayouts.TableCell
                    key={column.key}
                    flex={!column.width}
                    width={column.width}
                  >
                    {column.render(item)}
                  </TableLayouts.TableCell>
                ))}
              </TableLayouts.TableRow>
            );
          })}
        </GeneralLayouts.Section>
      )}
    </GeneralLayouts.Section>
  );
}

// ============================================================================
// DOCUMENT SETS TABLE - Table content for document sets view
// ============================================================================

interface DocumentSetsTableContentProps {
  documentSets: DocumentSetSummary[];
  selectedDocumentSetIds: number[];
  onDocumentSetToggle: (documentSetId: number) => void;
}

function DocumentSetsTableContent({
  documentSets,
  selectedDocumentSetIds,
  onDocumentSetToggle,
}: DocumentSetsTableContentProps) {
  const [searchValue, setSearchValue] = useState("");

  const filteredDocumentSets = useMemo(() => {
    if (!searchValue) return documentSets;
    const lower = searchValue.toLowerCase();
    return documentSets.filter((ds) => ds.name.toLowerCase().includes(lower));
  }, [documentSets, searchValue]);

  const columns: KnowledgeTableColumn<DocumentSetSummary>[] = [
    {
      key: "name",
      header: "Name",
      sortable: true,
      render: (ds) => (
        <GeneralLayouts.LineItemLayout
          icon={SvgFolder}
          title={ds.name}
          variant="secondary"
        />
      ),
    },
    {
      key: "sources",
      header: "Sources",
      width: 8,
      render: (ds) => (
        <TableLayouts.SourceIconsRow>
          {ds.cc_pair_summaries
            ?.slice(0, 4)
            .map((summary: CCPairSummary, idx: number) => {
              const sourceMetadata = getSourceMetadata(summary.source);
              return <sourceMetadata.icon key={idx} size={16} />;
            })}
          {(ds.cc_pair_summaries?.length ?? 0) > 4 && (
            <Text text03 secondaryBody>
              +{(ds.cc_pair_summaries?.length ?? 0) - 4}
            </Text>
          )}
        </TableLayouts.SourceIconsRow>
      ),
    },
  ];

  return (
    <KnowledgeTable
      items={filteredDocumentSets}
      columns={columns}
      getItemId={(ds) => ds.id}
      selectedIds={selectedDocumentSetIds}
      onToggleItem={(id) => onDocumentSetToggle(id as number)}
      searchValue={searchValue}
      onSearchChange={setSearchValue}
      searchPlaceholder="Search document sets..."
      emptyMessage="No document sets available."
      ariaLabelPrefix="document-set-row"
    />
  );
}

// ============================================================================
// SOURCES TABLE - Table content for connected sources view
// ============================================================================

interface SourceItem {
  source: ValidSources;
  name: string;
}

interface SourcesTableContentProps {
  source: ValidSources;
  isSelected: boolean;
  onToggle: () => void;
}

function SourcesTableContent({
  source,
  isSelected,
  onToggle,
}: SourcesTableContentProps) {
  const sourceMetadata = getSourceMetadata(source);

  const items: SourceItem[] = [
    {
      source,
      name: `All ${sourceMetadata.displayName} documents`,
    },
  ];

  const columns: KnowledgeTableColumn<SourceItem>[] = [
    {
      key: "name",
      header: "Name",
      sortable: true,
      render: (item) => {
        const metadata = getSourceMetadata(item.source);
        return (
          <GeneralLayouts.LineItemLayout
            icon={metadata.icon}
            title={item.name}
            variant="secondary"
          />
        );
      },
    },
    {
      key: "lastUpdated",
      header: "Last Updated",
      sortable: true,
      width: 8,
      render: () => (
        <Text text03 secondaryBody>
          —
        </Text>
      ),
    },
  ];

  return (
    <KnowledgeTable
      items={items}
      columns={columns}
      getItemId={(item) => item.source}
      selectedIds={isSelected ? [source] : []}
      onToggleItem={() => onToggle()}
      emptyMessage="No sources available."
    />
  );
}

// ============================================================================
// RECENT FILES TABLE - Table content for user files view
// ============================================================================

interface RecentFilesTableContentProps {
  allRecentFiles: ProjectFile[];
  selectedFileIds: string[];
  onToggleFile: (fileId: string) => void;
  onUploadChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  hasProcessingFiles: boolean;
}

function RecentFilesTableContent({
  allRecentFiles,
  selectedFileIds,
  onToggleFile,
  onUploadChange,
  hasProcessingFiles,
}: RecentFilesTableContentProps) {
  const [searchValue, setSearchValue] = useState("");

  const filteredFiles = useMemo(() => {
    if (!searchValue) return allRecentFiles;
    const lower = searchValue.toLowerCase();
    return allRecentFiles.filter((f) => f.name.toLowerCase().includes(lower));
  }, [allRecentFiles, searchValue]);

  const columns: KnowledgeTableColumn<ProjectFile>[] = [
    {
      key: "name",
      header: "Name",
      sortable: true,
      render: (file) => (
        <GeneralLayouts.LineItemLayout
          icon={SvgFiles}
          title={file.name}
          variant="secondary"
        />
      ),
    },
    {
      key: "lastUpdated",
      header: "Last Updated",
      sortable: true,
      width: 8,
      render: (file) => (
        <Text text03 secondaryBody>
          {timeAgo(file.last_accessed_at || file.created_at)}
        </Text>
      ),
    },
  ];

  const fileInputRef = React.useRef<HTMLInputElement>(null);

  return (
    <GeneralLayouts.Section gap={0.5} alignItems="stretch">
      <TableLayouts.HiddenInput
        inputRef={fileInputRef}
        type="file"
        multiple
        onChange={onUploadChange}
      />

      <KnowledgeTable
        items={filteredFiles}
        columns={columns}
        getItemId={(file) => file.id}
        selectedIds={selectedFileIds}
        onToggleItem={(id) => onToggleFile(id as string)}
        searchValue={searchValue}
        onSearchChange={setSearchValue}
        searchPlaceholder="Search files..."
        headerActions={
          <Button
            internal
            leftIcon={SvgPlusCircle}
            onClick={() => fileInputRef.current?.click()}
          >
            Add File
          </Button>
        }
        emptyMessage="No files available. Upload files to get started."
      />

      {hasProcessingFiles && (
        <GeneralLayouts.Section height="auto" alignItems="start">
          <Text as="p" text03 secondaryBody>
            Onyx is still processing your uploaded files. You can create the
            agent now, but it will not have access to all files until processing
            completes.
          </Text>
        </GeneralLayouts.Section>
      )}
    </GeneralLayouts.Section>
  );
}

// ============================================================================
// TWO-COLUMN LAYOUT - Sidebar + Table for detailed views
// ============================================================================

interface KnowledgeTwoColumnViewProps {
  activeView: KnowledgeView;
  activeSource?: ValidSources;
  connectedSources: ConnectedSource[];
  selectedSources: ValidSources[];
  selectedDocumentSetIds: number[];
  selectedFileIds: string[];
  documentSets: DocumentSetSummary[];
  allRecentFiles: ProjectFile[];
  onNavigateToRecent: () => void;
  onNavigateToDocumentSets: () => void;
  onNavigateToSource: (source: ValidSources) => void;
  onDocumentSetToggle: (id: number) => void;
  onSourceToggle: (source: ValidSources) => void;
  onFileToggle: (fileId: string) => void;
  onUploadChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  hasProcessingFiles: boolean;
}

const KnowledgeTwoColumnView = memo(function KnowledgeTwoColumnView({
  activeView,
  activeSource,
  connectedSources,
  selectedSources,
  selectedDocumentSetIds,
  selectedFileIds,
  documentSets,
  allRecentFiles,
  onNavigateToRecent,
  onNavigateToDocumentSets,
  onNavigateToSource,
  onDocumentSetToggle,
  onSourceToggle,
  onFileToggle,
  onUploadChange,
  hasProcessingFiles,
}: KnowledgeTwoColumnViewProps) {
  return (
    <TableLayouts.TwoColumnLayout minHeight={18.75}>
      <KnowledgeSidebar
        activeView={activeView}
        activeSource={activeSource}
        connectedSources={connectedSources}
        selectedSources={selectedSources}
        selectedDocumentSetIds={selectedDocumentSetIds}
        selectedFileIds={selectedFileIds}
        onNavigateToRecent={onNavigateToRecent}
        onNavigateToDocumentSets={onNavigateToDocumentSets}
        onNavigateToSource={onNavigateToSource}
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
            isSelected={selectedSources.includes(activeSource)}
            onToggle={() => onSourceToggle(activeSource)}
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
  );
});

// ============================================================================
// KNOWLEDGE ADD VIEW - Initial pill selection view
// ============================================================================

interface KnowledgeAddViewProps {
  connectedSources: ConnectedSource[];
  onNavigateToDocumentSets: () => void;
  onNavigateToRecent: () => void;
  onNavigateToSource: (source: ValidSources) => void;
  selectedDocumentSetIds: number[];
  selectedFileIds: string[];
  selectedSources: ValidSources[];
}

const KnowledgeAddView = memo(function KnowledgeAddView({
  connectedSources,
  onNavigateToDocumentSets,
  onNavigateToRecent,
  onNavigateToSource,
  selectedDocumentSetIds,
  selectedFileIds,
  selectedSources,
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
        <LineItem
          icon={SvgFolder}
          description="(deprecated)"
          onClick={onNavigateToDocumentSets}
          emphasized={selectedDocumentSetIds.length > 0}
          aria-label="knowledge-add-document-sets"
        >
          Document Sets
        </LineItem>

        <LineItem
          icon={SvgFiles}
          description="Recent or new uploads"
          onClick={onNavigateToRecent}
          emphasized={selectedFileIds.length > 0}
          aria-label="knowledge-add-files"
        >
          Your Files
        </LineItem>
      </GeneralLayouts.Section>

      {connectedSources.length > 0 && (
        <>
          <Text as="p" text03 secondaryBody>
            Connected Sources
          </Text>
          {connectedSources.map((connectedSource) => {
            const sourceMetadata = getSourceMetadata(connectedSource.source);
            const isSelected = selectedSources.includes(connectedSource.source);
            return (
              <LineItem
                key={connectedSource.source}
                icon={sourceMetadata.icon}
                onClick={() => onNavigateToSource(connectedSource.source)}
                emphasized={isSelected}
                aria-label={`knowledge-add-source-${connectedSource.source}`}
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

// ============================================================================
// KNOWLEDGE MAIN CONTENT - Empty state and preview
// ============================================================================

interface KnowledgeMainContentProps {
  enableKnowledge: boolean;
  hasAnyKnowledge: boolean;
  selectedDocumentSetIds: number[];
  selectedFileIds: string[];
  selectedSources: ValidSources[];
  documentSets: DocumentSetSummary[];
  allRecentFiles: ProjectFile[];
  connectedSources: ConnectedSource[];
  onAddKnowledge: () => void;
  onViewEdit: () => void;
  onFileClick?: (file: ProjectFile) => void;
}

const KnowledgeMainContent = memo(function KnowledgeMainContent({
  enableKnowledge,
  hasAnyKnowledge,
  selectedDocumentSetIds,
  selectedFileIds,
  selectedSources,
  documentSets,
  allRecentFiles,
  connectedSources,
  onAddKnowledge,
  onViewEdit,
  onFileClick,
}: KnowledgeMainContentProps) {
  if (!enableKnowledge) {
    return null;
  }

  if (!hasAnyKnowledge) {
    return (
      <GeneralLayouts.Section
        flexDirection="row"
        justifyContent="between"
        alignItems="center"
        height="auto"
      >
        <Text text03 secondaryBody>
          Add documents or connected sources to use for this agent.
        </Text>
        <IconButton
          icon={SvgPlusCircle}
          onClick={onAddKnowledge}
          tertiary
          aria-label="knowledge-add-button"
        />
      </GeneralLayouts.Section>
    );
  }

  // Has knowledge - show preview with count
  const totalSelected =
    selectedDocumentSetIds.length +
    selectedFileIds.length +
    selectedSources.length;

  return (
    <GeneralLayouts.Section
      flexDirection="row"
      justifyContent="between"
      alignItems="center"
      height="auto"
    >
      <Text as="p" text03 secondaryBody>
        {totalSelected} knowledge source{totalSelected !== 1 ? "s" : ""}{" "}
        selected
      </Text>
      <Button
        internal
        leftIcon={SvgArrowUpRight}
        onClick={onViewEdit}
        aria-label="knowledge-view-edit"
      >
        View / Edit
      </Button>
    </GeneralLayouts.Section>
  );
});

// ============================================================================
// MAIN COMPONENT - AgentKnowledgePane
// ============================================================================

interface AgentKnowledgePaneProps {
  enableKnowledge: boolean;
  onEnableKnowledgeChange: (enabled: boolean) => void;
  selectedSources: ValidSources[];
  onSourcesChange: (sources: ValidSources[]) => void;
  documentSets: DocumentSetSummary[];
  selectedDocumentSetIds: number[];
  onDocumentSetIdsChange: (ids: number[]) => void;
  selectedFileIds: string[];
  onFileIdsChange: (ids: string[]) => void;
  allRecentFiles: ProjectFile[];
  onFileClick?: (file: ProjectFile) => void;
  onUploadChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  hasProcessingFiles: boolean;
}

export default function AgentKnowledgePane({
  enableKnowledge,
  onEnableKnowledgeChange,
  selectedSources,
  onSourcesChange,
  documentSets,
  selectedDocumentSetIds,
  onDocumentSetIdsChange,
  selectedFileIds,
  onFileIdsChange,
  allRecentFiles,
  onFileClick,
  onUploadChange,
  hasProcessingFiles,
}: AgentKnowledgePaneProps) {
  // View state
  const [view, setView] = useState<KnowledgeView>("main");
  const [activeSource, setActiveSource] = useState<ValidSources | undefined>();

  // Get connected sources from CC pairs
  const { ccPairs } = useCCPairs();
  const connectedSources: ConnectedSource[] = useMemo(() => {
    if (!ccPairs || ccPairs.length === 0) return [];
    const sourceSet = new Set<ValidSources>();
    ccPairs.forEach((pair) => sourceSet.add(pair.source));
    return Array.from(sourceSet).map((source) => ({
      source,
      connectorCount: ccPairs.filter((p) => p.source === source).length,
    }));
  }, [ccPairs]);

  // Check if any knowledge is selected
  const hasAnyKnowledge =
    selectedDocumentSetIds.length > 0 ||
    selectedFileIds.length > 0 ||
    selectedSources.length > 0;

  // Navigation handlers - memoized to prevent unnecessary re-renders
  const handleNavigateToAdd = useCallback(() => setView("add"), []);
  const handleNavigateToMain = useCallback(() => setView("main"), []);
  const handleNavigateToDocumentSets = useCallback(
    () => setView("document-sets"),
    []
  );
  const handleNavigateToRecent = useCallback(() => setView("recent"), []);
  const handleNavigateToSource = useCallback((source: ValidSources) => {
    setActiveSource(source);
    setView("sources");
  }, []);

  // Toggle handlers - memoized to prevent unnecessary re-renders
  const handleDocumentSetToggle = useCallback(
    (documentSetId: number) => {
      const newIds = selectedDocumentSetIds.includes(documentSetId)
        ? selectedDocumentSetIds.filter((id) => id !== documentSetId)
        : [...selectedDocumentSetIds, documentSetId];
      onDocumentSetIdsChange(newIds);
    },
    [selectedDocumentSetIds, onDocumentSetIdsChange]
  );

  const handleSourceToggle = useCallback(
    (source: ValidSources) => {
      const newSources = selectedSources.includes(source)
        ? selectedSources.filter((s) => s !== source)
        : [...selectedSources, source];
      onSourcesChange(newSources);
    },
    [selectedSources, onSourcesChange]
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

  // Memoized content based on view - prevents unnecessary re-renders
  const renderedContent = useMemo(() => {
    switch (view) {
      case "main":
        return (
          <KnowledgeMainContent
            enableKnowledge={enableKnowledge}
            hasAnyKnowledge={hasAnyKnowledge}
            selectedDocumentSetIds={selectedDocumentSetIds}
            selectedFileIds={selectedFileIds}
            selectedSources={selectedSources}
            documentSets={documentSets}
            allRecentFiles={allRecentFiles}
            connectedSources={connectedSources}
            onAddKnowledge={handleNavigateToAdd}
            onViewEdit={handleNavigateToAdd}
            onFileClick={onFileClick}
          />
        );

      case "add":
        return (
          <KnowledgeAddView
            connectedSources={connectedSources}
            onNavigateToDocumentSets={handleNavigateToDocumentSets}
            onNavigateToRecent={handleNavigateToRecent}
            onNavigateToSource={handleNavigateToSource}
            selectedDocumentSetIds={selectedDocumentSetIds}
            selectedFileIds={selectedFileIds}
            selectedSources={selectedSources}
          />
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
            documentSets={documentSets}
            allRecentFiles={allRecentFiles}
            onNavigateToRecent={handleNavigateToRecent}
            onNavigateToDocumentSets={handleNavigateToDocumentSets}
            onNavigateToSource={handleNavigateToSource}
            onDocumentSetToggle={handleDocumentSetToggle}
            onSourceToggle={handleSourceToggle}
            onFileToggle={handleFileToggle}
            onUploadChange={onUploadChange}
            hasProcessingFiles={hasProcessingFiles}
          />
        );

      default:
        return null;
    }
  }, [
    view,
    activeSource,
    enableKnowledge,
    hasAnyKnowledge,
    selectedDocumentSetIds,
    selectedFileIds,
    selectedSources,
    documentSets,
    allRecentFiles,
    connectedSources,
    hasProcessingFiles,
    onFileClick,
    onUploadChange,
    handleNavigateToAdd,
    handleNavigateToDocumentSets,
    handleNavigateToRecent,
    handleNavigateToSource,
    handleDocumentSetToggle,
    handleSourceToggle,
    handleFileToggle,
  ]);

  return (
    <GeneralLayouts.Section gap={0.5} alignItems="stretch" height="auto">
      <InputLayouts.Title
        title="Knowledge"
        description="Add specific connectors and documents for this agent to use to inform its responses."
      />

      <Card>
        <GeneralLayouts.Section gap={0.5} alignItems="stretch" height="auto">
          <InputLayouts.Horizontal
            title="Use Knowledge"
            description="Let this agent reference these documents to inform its responses."
          >
            <Switch
              name="enable_knowledge"
              checked={enableKnowledge}
              onCheckedChange={onEnableKnowledgeChange}
            />
          </InputLayouts.Horizontal>

          {renderedContent}
        </GeneralLayouts.Section>
      </Card>
    </GeneralLayouts.Section>
  );
}
