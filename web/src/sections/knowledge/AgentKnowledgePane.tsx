"use client";

import React, {
  useState,
  useMemo,
  useEffect,
  useCallback,
  useRef,
  memo,
} from "react";
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
  SvgChevronRight,
  SvgFileText,
  SvgEye,
  SvgXCircle,
} from "@opal/icons";
import type { CCPairSummary } from "@/lib/types";
import { getSourceMetadata } from "@/lib/sources";
import { ValidSources, DocumentSetSummary } from "@/lib/types";
import useCCPairs from "@/hooks/useCCPairs";
import {
  ConnectedSource,
  HierarchyNodeSummary,
  DocumentSummary,
  DocumentPageCursor,
} from "@/lib/hierarchy/types";
import {
  fetchHierarchyNodes,
  fetchHierarchyNodeDocuments,
} from "@/lib/hierarchy/api";
import { ProjectFile } from "@/app/app/projects/projectsService";
import { AttachedDocumentSnapshot } from "@/app/admin/assistants/interfaces";
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
// HIERARCHY ITEM - Union type for folders and documents in the table
// ============================================================================

type HierarchyItem =
  | { type: "folder"; data: HierarchyNodeSummary }
  | { type: "document"; data: DocumentSummary };

// ============================================================================
// HIERARCHY BREADCRUMB - Navigation path for folder hierarchy
// ============================================================================

interface HierarchyBreadcrumbProps {
  source: ValidSources;
  path: HierarchyNodeSummary[];
  onNavigateToRoot: () => void;
  onNavigateToNode: (node: HierarchyNodeSummary, index: number) => void;
}

function HierarchyBreadcrumb({
  source,
  path,
  onNavigateToRoot,
  onNavigateToNode,
}: HierarchyBreadcrumbProps) {
  const sourceMetadata = getSourceMetadata(source);
  const MAX_VISIBLE_SEGMENTS = 3;

  // Determine which segments to show
  const shouldCollapse = path.length > MAX_VISIBLE_SEGMENTS;
  const visiblePath = shouldCollapse
    ? path.slice(path.length - MAX_VISIBLE_SEGMENTS + 1)
    : path;
  const collapsedCount = shouldCollapse
    ? path.length - MAX_VISIBLE_SEGMENTS + 1
    : 0;

  return (
    <GeneralLayouts.Section
      flexDirection="row"
      justifyContent="start"
      alignItems="center"
      gap={0.25}
      height="auto"
    >
      {/* Root source link */}
      <button
        onClick={onNavigateToRoot}
        className="hover:underline cursor-pointer"
      >
        <Text text03 secondaryBody={path.length > 0}>
          {sourceMetadata.displayName}
        </Text>
      </button>

      {/* Collapsed indicator */}
      {shouldCollapse && (
        <>
          <SvgChevronRight size={12} className="stroke-text-04" />
          <Text text03 secondaryBody>
            ...
          </Text>
        </>
      )}

      {/* Visible path segments */}
      {visiblePath.map((node, visibleIndex) => {
        const actualIndex = shouldCollapse
          ? collapsedCount + visibleIndex
          : visibleIndex;
        const isLast = actualIndex === path.length - 1;

        return (
          <React.Fragment key={node.id}>
            <SvgChevronRight size={12} className="stroke-text-04" />
            {isLast ? (
              <Text text03>{node.title}</Text>
            ) : (
              <button
                onClick={() => onNavigateToNode(node, actualIndex)}
                className="hover:underline cursor-pointer"
              >
                <Text text03 secondaryBody>
                  {node.title}
                </Text>
              </button>
            )}
          </React.Fragment>
        );
      })}
    </GeneralLayouts.Section>
  );
}

// ============================================================================
// SOURCE HIERARCHY BROWSER - Browsable folder/document hierarchy for a source
// ============================================================================

interface SourceHierarchyBrowserProps {
  source: ValidSources;
  selectedDocumentIds: string[];
  onToggleDocument: (documentId: string) => void;
  onSetDocumentIds: (ids: string[]) => void;
  selectedFolderIds: number[];
  onToggleFolder: (folderId: number) => void;
  onSetFolderIds: (ids: number[]) => void;
  onDeselectAllDocuments: () => void;
  onDeselectAllFolders: () => void;
  initialAttachedDocuments?: AttachedDocumentSnapshot[];
}

function SourceHierarchyBrowser({
  source,
  selectedDocumentIds,
  onToggleDocument,
  onSetDocumentIds,
  selectedFolderIds,
  onToggleFolder,
  onSetFolderIds,
  onDeselectAllDocuments,
  onDeselectAllFolders,
  initialAttachedDocuments,
}: SourceHierarchyBrowserProps) {
  // State for hierarchy nodes (loaded once per source)
  const [allNodes, setAllNodes] = useState<HierarchyNodeSummary[]>([]);
  const [isLoadingNodes, setIsLoadingNodes] = useState(false);
  const [nodesError, setNodesError] = useState<string | null>(null);

  // State for current navigation path
  const [path, setPath] = useState<HierarchyNodeSummary[]>([]);

  // State for documents (paginated)
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [nextCursor, setNextCursor] = useState<DocumentPageCursor | null>(null);
  const [isLoadingDocuments, setIsLoadingDocuments] = useState(false);
  const [hasMoreDocuments, setHasMoreDocuments] = useState(true);

  // Search state
  const [searchValue, setSearchValue] = useState("");

  // View selected only filter state
  const [viewSelectedOnly, setViewSelectedOnly] = useState(false);

  // Store path before entering view selected mode so we can restore it
  const [savedPath, setSavedPath] = useState<HierarchyNodeSummary[]>([]);

  // Store selected document details (for showing all selected documents in view selected mode)
  const [selectedDocumentDetails, setSelectedDocumentDetails] = useState<
    Map<string, DocumentSummary>
  >(() => {
    // Initialize with initial attached documents if provided
    if (initialAttachedDocuments && initialAttachedDocuments.length > 0) {
      const initialMap = new Map<string, DocumentSummary>();
      initialAttachedDocuments.forEach((doc) => {
        initialMap.set(doc.id, {
          id: doc.id,
          title: doc.title,
          link: doc.link,
          parent_id: doc.parent_id,
          last_modified: doc.last_modified,
          last_synced: doc.last_synced,
        });
      });
      return initialMap;
    }
    return new Map();
  });

  // Ref for scroll container
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  // Get current parent node ID (null for root)
  const lastPathNode = path[path.length - 1];
  const currentParentId = lastPathNode ? lastPathNode.id : null;

  // Load hierarchy nodes when source changes
  useEffect(() => {
    const loadNodes = async () => {
      setIsLoadingNodes(true);
      setNodesError(null);
      setAllNodes([]);
      setPath([]);
      setDocuments([]);
      setNextCursor(null);
      setHasMoreDocuments(true);

      try {
        const response = await fetchHierarchyNodes(source);
        setAllNodes(response.nodes);
      } catch (error) {
        setNodesError(
          error instanceof Error ? error.message : "Failed to load folders"
        );
      } finally {
        setIsLoadingNodes(false);
      }
    };

    loadNodes();
  }, [source]);

  // Load documents when current path changes
  useEffect(() => {
    const loadDocuments = async () => {
      // Skip if no nodes loaded yet (still loading hierarchy)
      if (allNodes.length === 0 && !nodesError) return;

      setIsLoadingDocuments(true);
      setDocuments([]);
      setNextCursor(null);
      setHasMoreDocuments(true);

      try {
        // We need a parent hierarchy node to fetch documents
        // For root level, we need to find the root node(s)
        const parentNodeId = currentParentId;
        if (parentNodeId === null) {
          // At root level - find root nodes (nodes with no parent)
          const rootNodes = allNodes.filter((n) => n.parent_id === null);
          if (rootNodes.length === 0) {
            setHasMoreDocuments(false);
            return;
          }
          // For now, just don't load documents at root level
          // Documents are always children of a hierarchy node
          setHasMoreDocuments(false);
          return;
        }

        const response = await fetchHierarchyNodeDocuments({
          parent_hierarchy_node_id: parentNodeId,
          cursor: null,
        });

        setDocuments(response.documents);
        setNextCursor(response.next_cursor);
        setHasMoreDocuments(response.next_cursor !== null);
      } catch (error) {
        console.error("Failed to load documents:", error);
      } finally {
        setIsLoadingDocuments(false);
      }
    };

    loadDocuments();
  }, [currentParentId, allNodes, nodesError]);

  // Load more documents (for infinite scroll)
  const loadMoreDocuments = useCallback(async () => {
    if (!hasMoreDocuments || isLoadingDocuments || !nextCursor) return;
    if (currentParentId === null) return;

    setIsLoadingDocuments(true);

    try {
      const response = await fetchHierarchyNodeDocuments({
        parent_hierarchy_node_id: currentParentId,
        cursor: nextCursor,
      });

      setDocuments((prev) => [...prev, ...response.documents]);
      setNextCursor(response.next_cursor);
      setHasMoreDocuments(response.next_cursor !== null);
    } catch (error) {
      console.error("Failed to load more documents:", error);
    } finally {
      setIsLoadingDocuments(false);
    }
  }, [currentParentId, nextCursor, hasMoreDocuments, isLoadingDocuments]);

  // Infinite scroll handler
  const handleScroll = useCallback(() => {
    const container = scrollContainerRef.current;
    if (!container) return;

    const { scrollTop, scrollHeight, clientHeight } = container;
    const scrollThreshold = 100; // Load more when within 100px of bottom

    if (scrollHeight - scrollTop - clientHeight < scrollThreshold) {
      loadMoreDocuments();
    }
  }, [loadMoreDocuments]);

  // Populate selectedDocumentDetails for any documents that are already selected
  // but don't have their details stored (e.g., when editing an existing agent)
  useEffect(() => {
    if (documents.length === 0) return;

    const missingDetails = documents.filter(
      (doc) =>
        selectedDocumentIds.includes(doc.id) &&
        !selectedDocumentDetails.has(doc.id)
    );

    if (missingDetails.length > 0) {
      setSelectedDocumentDetails((prev) => {
        const updated = new Map(prev);
        missingDetails.forEach((doc) => updated.set(doc.id, doc));
        return updated;
      });
    }
  }, [documents, selectedDocumentIds, selectedDocumentDetails]);

  // Get child folders of the current path
  const childFolders = useMemo(() => {
    return allNodes.filter((node) => node.parent_id === currentParentId);
  }, [allNodes, currentParentId]);

  // Combine folders and documents into items list
  const items: HierarchyItem[] = useMemo(() => {
    const folderItems: HierarchyItem[] = childFolders.map((node) => ({
      type: "folder",
      data: node,
    }));
    const documentItems: HierarchyItem[] = documents.map((doc) => ({
      type: "document",
      data: doc,
    }));
    return [...folderItems, ...documentItems];
  }, [childFolders, documents]);

  // Filter items by search and view selected mode
  const filteredItems = useMemo(() => {
    let result: HierarchyItem[];

    if (viewSelectedOnly) {
      // In view selected mode, show ALL selected items from anywhere in the hierarchy
      const selectedFolders: HierarchyItem[] = allNodes
        .filter((node) => selectedFolderIds.includes(node.id))
        .map((node) => ({ type: "folder" as const, data: node }));

      const selectedDocs: HierarchyItem[] = selectedDocumentIds
        .map((docId) => selectedDocumentDetails.get(docId))
        .filter((doc): doc is DocumentSummary => doc !== undefined)
        .map((doc) => ({ type: "document" as const, data: doc }));

      result = [...selectedFolders, ...selectedDocs];
    } else {
      // Normal mode: show items from current folder
      result = items;
    }

    // Filter by search
    if (searchValue) {
      const lower = searchValue.toLowerCase();
      result = result.filter((item) =>
        item.data.title.toLowerCase().includes(lower)
      );
    }

    return result;
  }, [
    items,
    searchValue,
    viewSelectedOnly,
    selectedFolderIds,
    selectedDocumentIds,
    allNodes,
    selectedDocumentDetails,
  ]);

  // Total selected count for footer
  const totalSelectedCount =
    selectedDocumentIds.length + selectedFolderIds.length;

  // Header checkbox state: count how many visible items are selected
  const visibleSelectedCount = useMemo(() => {
    return filteredItems.filter((item) => {
      const isFolder = item.type === "folder";
      if (isFolder) {
        return selectedFolderIds.includes(item.data.id as number);
      }
      return selectedDocumentIds.includes(item.data.id as string);
    }).length;
  }, [filteredItems, selectedFolderIds, selectedDocumentIds]);

  const allVisibleSelected =
    filteredItems.length > 0 && visibleSelectedCount === filteredItems.length;
  const someVisibleSelected =
    visibleSelectedCount > 0 && visibleSelectedCount < filteredItems.length;

  // Handler for header checkbox click
  const handleHeaderCheckboxClick = () => {
    // Get visible folders and documents
    const visibleFolders = filteredItems.filter(
      (item) => item.type === "folder"
    );
    const visibleDocs = filteredItems.filter(
      (item) => item.type === "document"
    );
    const visibleFolderIds = visibleFolders.map(
      (item) => item.data.id as number
    );
    const visibleDocumentIds = visibleDocs.map(
      (item) => item.data.id as string
    );

    if (allVisibleSelected) {
      // Deselect all visible items by removing them from the selected arrays
      const newFolderIds = selectedFolderIds.filter(
        (id) => !visibleFolderIds.includes(id)
      );
      const newDocumentIds = selectedDocumentIds.filter(
        (id) => !visibleDocumentIds.includes(id)
      );
      onSetFolderIds(newFolderIds);
      onSetDocumentIds(newDocumentIds);

      // Remove deselected documents from details map
      setSelectedDocumentDetails((prev) => {
        const updated = new Map(prev);
        visibleDocumentIds.forEach((id) => updated.delete(id));
        return updated;
      });

      // If we deselected everything, exit view selected mode
      if (newFolderIds.length === 0 && newDocumentIds.length === 0) {
        setViewSelectedOnly(false);
      }
    } else {
      // Select all visible items by adding them to the selected arrays
      const newFolderIds = [
        ...selectedFolderIds,
        ...visibleFolderIds.filter((id) => !selectedFolderIds.includes(id)),
      ];
      const newDocumentIds = [
        ...selectedDocumentIds,
        ...visibleDocumentIds.filter((id) => !selectedDocumentIds.includes(id)),
      ];
      onSetFolderIds(newFolderIds);
      onSetDocumentIds(newDocumentIds);

      // Store details for newly selected documents
      setSelectedDocumentDetails((prev) => {
        const updated = new Map(prev);
        visibleDocs.forEach((item) => {
          const docId = item.data.id as string;
          if (!prev.has(docId)) {
            updated.set(docId, item.data as DocumentSummary);
          }
        });
        return updated;
      });
    }
  };

  // Navigation handlers
  const handleNavigateToRoot = () => setPath([]);

  const handleNavigateToNode = (node: HierarchyNodeSummary, index: number) => {
    setPath((prev) => prev.slice(0, index + 1));
  };

  const handleClickIntoFolder = (folder: HierarchyNodeSummary) => {
    if (viewSelectedOnly) {
      // Exit view selected mode and navigate to the folder
      // We need to build the path to this folder from root
      const buildPathToFolder = (
        targetId: number
      ): HierarchyNodeSummary[] | null => {
        const node = allNodes.find((n) => n.id === targetId);
        if (!node) return null;
        if (node.parent_id === null) return [node];
        const parentPath = buildPathToFolder(node.parent_id);
        if (!parentPath) return null;
        return [...parentPath, node];
      };
      const pathToFolder = buildPathToFolder(folder.id);
      if (pathToFolder) {
        setPath(pathToFolder);
      } else {
        // Fallback: just set the folder as the path
        setPath([folder]);
      }
      setViewSelectedOnly(false);
    } else {
      setPath((prev) => [...prev, folder]);
    }
  };

  // Handler for deselecting all items
  const handleDeselectAll = () => {
    onDeselectAllDocuments();
    onDeselectAllFolders();
    setSelectedDocumentDetails(new Map());
    setViewSelectedOnly(false);
  };

  // Handler for toggling view selected mode
  const handleToggleViewSelected = () => {
    setViewSelectedOnly((prev) => {
      if (!prev) {
        // Entering view selected mode - save current path
        setSavedPath(path);
      } else {
        // Exiting view selected mode - restore saved path
        setPath(savedPath);
      }
      return !prev;
    });
  };

  // Render loading state
  if (isLoadingNodes) {
    return (
      <GeneralLayouts.Section height="auto" padding={1}>
        <Text text03 secondaryBody>
          Loading folders...
        </Text>
      </GeneralLayouts.Section>
    );
  }

  // Render error state
  if (nodesError) {
    return (
      <GeneralLayouts.Section height="auto" padding={1}>
        <Text text03 secondaryBody>
          {nodesError}
        </Text>
      </GeneralLayouts.Section>
    );
  }

  return (
    <GeneralLayouts.Section gap={0} alignItems="stretch" justifyContent="start">
      {/* Header with search */}
      <GeneralLayouts.Section
        flexDirection="row"
        justifyContent="start"
        alignItems="center"
        gap={0.5}
        height="auto"
      >
        <GeneralLayouts.Section height="auto" width="fit">
          <InputTypeIn
            leftSearchIcon
            value={searchValue}
            onChange={(e) => setSearchValue(e.target.value)}
            placeholder="Search..."
            variant="internal"
          />
        </GeneralLayouts.Section>
      </GeneralLayouts.Section>

      {/* Breadcrumb OR "Selected items" pill - mutually exclusive */}
      {viewSelectedOnly ? (
        <>
          <Spacer rem={0.5} />
          <Button action tertiary onClick={handleToggleViewSelected}>
            Selected items
          </Button>
        </>
      ) : (
        (path.length > 0 || allNodes.length > 0) && (
          <>
            <Spacer rem={0.5} />
            <HierarchyBreadcrumb
              source={source}
              path={path}
              onNavigateToRoot={handleNavigateToRoot}
              onNavigateToNode={handleNavigateToNode}
            />
          </>
        )
      )}

      <Spacer rem={0.5} />

      {/* Table header */}
      <TableLayouts.TableRow>
        <TableLayouts.CheckboxCell>
          {filteredItems.length > 0 && (
            <Checkbox
              checked={allVisibleSelected}
              indeterminate={someVisibleSelected}
              onCheckedChange={handleHeaderCheckboxClick}
            />
          )}
        </TableLayouts.CheckboxCell>
        <TableLayouts.TableCell flex>
          <GeneralLayouts.Section
            flexDirection="row"
            justifyContent="start"
            alignItems="center"
            gap={0.25}
            height="auto"
          >
            <Text secondaryBody text03>
              Name
            </Text>
            <Text text03 secondaryBody>
              ↕
            </Text>
          </GeneralLayouts.Section>
        </TableLayouts.TableCell>
        <TableLayouts.TableCell width={8}>
          <GeneralLayouts.Section
            flexDirection="row"
            justifyContent="start"
            alignItems="center"
            gap={0.25}
            height="auto"
          >
            <Text secondaryBody text03>
              Last Updated
            </Text>
            <Text text03 secondaryBody>
              ↕
            </Text>
          </GeneralLayouts.Section>
        </TableLayouts.TableCell>
      </TableLayouts.TableRow>

      <Separator noPadding />

      {/* Scrollable table body */}
      <div
        ref={scrollContainerRef}
        onScroll={handleScroll}
        className="overflow-y-auto max-h-[20rem]"
      >
        {filteredItems.length === 0 && !isLoadingDocuments ? (
          <GeneralLayouts.Section height="auto" padding={1}>
            <Text text03 secondaryBody>
              {path.length === 0
                ? "Select a folder to browse documents."
                : "No items in this folder."}
            </Text>
          </GeneralLayouts.Section>
        ) : (
          <GeneralLayouts.Section gap={0} alignItems="stretch" height="auto">
            {filteredItems.map((item) => {
              const isFolder = item.type === "folder";
              const id = isFolder ? `folder-${item.data.id}` : item.data.id;
              const isSelected = isFolder
                ? selectedFolderIds.includes(item.data.id as number)
                : selectedDocumentIds.includes(item.data.id as string);

              const handleRowClick = () => {
                if (isFolder) {
                  onToggleFolder(item.data.id as number);
                } else {
                  const docId = item.data.id as string;
                  const isCurrentlySelected =
                    selectedDocumentIds.includes(docId);
                  if (!isCurrentlySelected) {
                    // Document is being selected - store its details
                    setSelectedDocumentDetails((prev) => {
                      const updated = new Map(prev);
                      updated.set(docId, item.data as DocumentSummary);
                      return updated;
                    });
                  } else {
                    // Document is being deselected - remove from details
                    setSelectedDocumentDetails((prev) => {
                      const updated = new Map(prev);
                      updated.delete(docId);
                      return updated;
                    });
                  }
                  onToggleDocument(docId);
                }
              };

              // For files: show checked checkbox when selected, file icon when not
              // For folders: always show folder icon
              const renderIcon = () => {
                if (isFolder) {
                  return <SvgFolder size={16} />;
                }
                if (isSelected) {
                  // Use actual Checkbox component for proper visual (blue fill + white check)
                  return <Checkbox checked={true} />;
                }
                return <SvgFileText size={16} />;
              };

              return (
                <TableLayouts.TableRow
                  key={id}
                  selected={isSelected}
                  onClick={handleRowClick}
                >
                  <TableLayouts.CheckboxCell>
                    {renderIcon()}
                  </TableLayouts.CheckboxCell>
                  <TableLayouts.TableCell flex>
                    <GeneralLayouts.Section
                      flexDirection="row"
                      justifyContent="start"
                      alignItems="center"
                      gap={0.25}
                      height="auto"
                      width="fit"
                    >
                      <Truncated>{item.data.title}</Truncated>
                      {isFolder && (
                        <IconButton
                          icon={SvgChevronRight}
                          internal
                          onClick={(e) => {
                            e.stopPropagation();
                            handleClickIntoFolder(
                              item.data as HierarchyNodeSummary
                            );
                          }}
                        />
                      )}
                    </GeneralLayouts.Section>
                  </TableLayouts.TableCell>
                  <TableLayouts.TableCell width={8}>
                    <Text text03 secondaryBody>
                      {isFolder
                        ? "—"
                        : timeAgo(
                            (item.data as DocumentSummary).last_modified
                          ) || "—"}
                    </Text>
                  </TableLayouts.TableCell>
                </TableLayouts.TableRow>
              );
            })}

            {/* Loading more indicator */}
            {isLoadingDocuments && documents.length > 0 && (
              <GeneralLayouts.Section height="auto" padding={0.5}>
                <Text text03 secondaryBody>
                  Loading more...
                </Text>
              </GeneralLayouts.Section>
            )}
          </GeneralLayouts.Section>
        )}
      </div>

      {/* Table footer - only show when items are selected */}
      {totalSelectedCount > 0 && (
        <>
          <Spacer rem={0.5} />
          <GeneralLayouts.Section
            flexDirection="row"
            justifyContent="start"
            alignItems="center"
            gap={0.5}
            height="auto"
          >
            <Text text03 secondaryBody>
              {totalSelectedCount} {totalSelectedCount === 1 ? "item" : "items"}{" "}
              selected
            </Text>
            <IconButton
              icon={SvgEye}
              internal={!viewSelectedOnly}
              action={viewSelectedOnly}
              tertiary={viewSelectedOnly}
              onClick={handleToggleViewSelected}
            />
            <IconButton
              icon={SvgXCircle}
              internal
              onClick={handleDeselectAll}
            />
          </GeneralLayouts.Section>
        </>
      )}
    </GeneralLayouts.Section>
  );
}

interface SourcesTableContentProps {
  source: ValidSources;
  selectedDocumentIds: string[];
  onToggleDocument: (documentId: string) => void;
  onSetDocumentIds: (ids: string[]) => void;
  selectedFolderIds: number[];
  onToggleFolder: (folderId: number) => void;
  onSetFolderIds: (ids: number[]) => void;
  onDeselectAllDocuments: () => void;
  onDeselectAllFolders: () => void;
  initialAttachedDocuments?: AttachedDocumentSnapshot[];
}

function SourcesTableContent({
  source,
  selectedDocumentIds,
  onToggleDocument,
  onSetDocumentIds,
  selectedFolderIds,
  onToggleFolder,
  onSetFolderIds,
  onDeselectAllDocuments,
  onDeselectAllFolders,
  initialAttachedDocuments,
}: SourcesTableContentProps) {
  return (
    <GeneralLayouts.Section gap={0.5} alignItems="stretch">
      {/* Hierarchy browser */}
      <SourceHierarchyBrowser
        source={source}
        selectedDocumentIds={selectedDocumentIds}
        onToggleDocument={onToggleDocument}
        onSetDocumentIds={onSetDocumentIds}
        selectedFolderIds={selectedFolderIds}
        onToggleFolder={onToggleFolder}
        onSetFolderIds={onSetFolderIds}
        initialAttachedDocuments={initialAttachedDocuments}
        onDeselectAllDocuments={onDeselectAllDocuments}
        onDeselectAllFolders={onDeselectAllFolders}
      />
    </GeneralLayouts.Section>
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
  selectedDocumentIds: string[];
  selectedFolderIds: number[];
  documentSets: DocumentSetSummary[];
  allRecentFiles: ProjectFile[];
  onNavigateToRecent: () => void;
  onNavigateToDocumentSets: () => void;
  onNavigateToSource: (source: ValidSources) => void;
  onDocumentSetToggle: (id: number) => void;
  onSourceToggle: (source: ValidSources) => void;
  onFileToggle: (fileId: string) => void;
  onToggleDocument: (documentId: string) => void;
  onToggleFolder: (folderId: number) => void;
  onSetDocumentIds: (ids: string[]) => void;
  onSetFolderIds: (ids: number[]) => void;
  onDeselectAllDocuments: () => void;
  onDeselectAllFolders: () => void;
  onUploadChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  hasProcessingFiles: boolean;
  initialAttachedDocuments?: AttachedDocumentSnapshot[];
}

const KnowledgeTwoColumnView = memo(function KnowledgeTwoColumnView({
  activeView,
  activeSource,
  connectedSources,
  selectedSources,
  selectedDocumentSetIds,
  selectedFileIds,
  selectedDocumentIds,
  selectedFolderIds,
  documentSets,
  allRecentFiles,
  onNavigateToRecent,
  onNavigateToDocumentSets,
  onNavigateToSource,
  onDocumentSetToggle,
  onSourceToggle,
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
            selectedDocumentIds={selectedDocumentIds}
            onToggleDocument={onToggleDocument}
            onSetDocumentIds={onSetDocumentIds}
            selectedFolderIds={selectedFolderIds}
            onToggleFolder={onToggleFolder}
            onSetFolderIds={onSetFolderIds}
            onDeselectAllDocuments={onDeselectAllDocuments}
            onDeselectAllFolders={onDeselectAllFolders}
            initialAttachedDocuments={initialAttachedDocuments}
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
  selectedDocumentIds: string[];
  selectedFolderIds: number[];
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
  selectedDocumentIds,
  selectedFolderIds,
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
    selectedDocumentIds.length +
    selectedFolderIds.length +
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
  // Initial attached documents for existing agents (to populate selectedDocumentDetails)
  initialAttachedDocuments?: AttachedDocumentSnapshot[];
}

export default function AgentKnowledgePane({
  enableKnowledge,
  onEnableKnowledgeChange,
  selectedSources,
  onSourcesChange,
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
  onFileClick,
  onUploadChange,
  hasProcessingFiles,
  initialAttachedDocuments,
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
    selectedDocumentIds.length > 0 ||
    selectedFolderIds.length > 0 ||
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

  // Memoized content based on view - prevents unnecessary re-renders
  const renderedContent = useMemo(() => {
    switch (view) {
      case "main":
        return (
          <KnowledgeMainContent
            enableKnowledge={enableKnowledge}
            hasAnyKnowledge={hasAnyKnowledge}
            selectedDocumentSetIds={selectedDocumentSetIds}
            selectedDocumentIds={selectedDocumentIds}
            selectedFolderIds={selectedFolderIds}
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
            selectedDocumentIds={selectedDocumentIds}
            selectedFolderIds={selectedFolderIds}
            documentSets={documentSets}
            allRecentFiles={allRecentFiles}
            onNavigateToRecent={handleNavigateToRecent}
            onNavigateToDocumentSets={handleNavigateToDocumentSets}
            onNavigateToSource={handleNavigateToSource}
            onDocumentSetToggle={handleDocumentSetToggle}
            onSourceToggle={handleSourceToggle}
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
    selectedDocumentIds,
    selectedFolderIds,
    selectedFileIds,
    selectedSources,
    documentSets,
    allRecentFiles,
    connectedSources,
    hasProcessingFiles,
    initialAttachedDocuments,
    onFileClick,
    onUploadChange,
    onDocumentIdsChange,
    onFolderIdsChange,
    handleNavigateToAdd,
    handleNavigateToDocumentSets,
    handleNavigateToRecent,
    handleNavigateToSource,
    handleDocumentSetToggle,
    handleSourceToggle,
    handleFileToggle,
    handleDocumentToggle,
    handleFolderToggle,
    handleDeselectAllDocuments,
    handleDeselectAllFolders,
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
