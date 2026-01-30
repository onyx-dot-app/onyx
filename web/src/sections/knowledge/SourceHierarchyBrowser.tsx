"use client";

import React, {
  useState,
  useMemo,
  useEffect,
  useCallback,
  useRef,
} from "react";
import * as GeneralLayouts from "@/layouts/general-layouts";
import * as TableLayouts from "@/layouts/table-layouts";
import Button from "@/refresh-components/buttons/Button";
import IconButton from "@/refresh-components/buttons/IconButton";
import Text from "@/refresh-components/texts/Text";
import Truncated from "@/refresh-components/texts/Truncated";
import Separator from "@/refresh-components/Separator";
import Checkbox from "@/refresh-components/inputs/Checkbox";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import {
  SvgFolder,
  SvgChevronRight,
  SvgFileText,
  SvgEye,
  SvgXCircle,
} from "@opal/icons";
import { getSourceMetadata } from "@/lib/sources";
import { ValidSources } from "@/lib/types";
import {
  HierarchyNodeSummary,
  DocumentSummary,
  DocumentPageCursor,
  HierarchyItem,
  HierarchyBreadcrumbProps,
} from "@/lib/hierarchy/interfaces";
import {
  fetchHierarchyNodes,
  fetchHierarchyNodeDocuments,
} from "@/lib/hierarchy/svc";
import { AttachedDocumentSnapshot } from "@/app/admin/assistants/interfaces";
import { timeAgo } from "@/lib/time";
import Spacer from "@/refresh-components/Spacer";

// ============================================================================
// HIERARCHY BREADCRUMB - Navigation path for folder hierarchy
// ============================================================================

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
      {path.length > 0 ? (
        <Button tertiary onClick={onNavigateToRoot}>
          {sourceMetadata.displayName}
        </Button>
      ) : (
        <Text text03>{sourceMetadata.displayName}</Text>
      )}

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
              <Button
                tertiary
                onClick={() => onNavigateToNode(node, actualIndex)}
              >
                {node.title}
              </Button>
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

export interface SourceHierarchyBrowserProps {
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

export default function SourceHierarchyBrowser({
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
  // Note: useState (not useMemo) because this is modified independently when users select/deselect documents
  const [selectedDocumentDetails, setSelectedDocumentDetails] = useState<
    Map<string, DocumentSummary>
  >(() => new Map(initialAttachedDocuments?.map((doc) => [doc.id, doc]) ?? []));

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

  // Handler for clicking a row (folder or document)
  const handleItemClick = (item: HierarchyItem) => {
    if (item.type === "folder") {
      onToggleFolder(item.data.id);
      return;
    }
    const docId = item.data.id;
    const isCurrentlySelected = selectedDocumentIds.includes(docId);
    if (isCurrentlySelected) {
      setSelectedDocumentDetails((prev) => {
        const updated = new Map(prev);
        updated.delete(docId);
        return updated;
      });
    } else {
      setSelectedDocumentDetails((prev) => {
        const updated = new Map(prev);
        updated.set(docId, item.data);
        return updated;
      });
    }
    onToggleDocument(docId);
  };

  // Get the icon for a hierarchy item row
  const getItemIcon = (item: HierarchyItem, isSelected: boolean) => {
    if (item.type === "folder") {
      return <SvgFolder size={16} />;
    }
    if (isSelected) {
      return <Checkbox checked={true} />;
    }
    return <SvgFileText size={16} />;
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

              return (
                <TableLayouts.TableRow
                  key={id}
                  selected={isSelected}
                  onClick={() => handleItemClick(item)}
                >
                  <TableLayouts.CheckboxCell>
                    {getItemIcon(item, isSelected)}
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
