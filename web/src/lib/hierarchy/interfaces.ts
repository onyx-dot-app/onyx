import { ValidSources } from "@/lib/types";

// Sort options for document pagination
export type DocumentSortField = "name" | "last_updated";
export type DocumentSortDirection = "asc" | "desc";
export type FolderPosition = "on_top" | "mixed";

// Hierarchy Node types matching backend models
export interface HierarchyNodeSummary {
  id: number;
  title: string;
  link: string | null;
  parent_id: number | null;
}

export interface HierarchyNodesRequest {
  source: ValidSources;
}

export interface HierarchyNodesResponse {
  nodes: HierarchyNodeSummary[];
}

// Document types for hierarchy
export interface DocumentPageCursor {
  // Fields for last_updated sorting
  last_modified?: string | null;
  last_synced?: string | null;
  // Field for name sorting
  name?: string | null;
  // Document ID for tie-breaking (always required)
  document_id: string;
}

export interface HierarchyNodeDocumentsRequest {
  parent_hierarchy_node_id: number;
  cursor?: DocumentPageCursor | null;
  sort_field?: DocumentSortField;
  sort_direction?: DocumentSortDirection;
  folder_position?: FolderPosition;
}

export interface DocumentSummary {
  id: string;
  title: string;
  link: string | null;
  parent_id: number | null;
  last_modified: string | null;
  last_synced: string | null;
}

export interface HierarchyNodeDocumentsResponse {
  documents: DocumentSummary[];
  next_cursor: DocumentPageCursor | null;
  page_size: number;
  sort_field: DocumentSortField;
  sort_direction: DocumentSortDirection;
  folder_position: FolderPosition;
}

// Connected source type for display
export interface ConnectedSource {
  source: ValidSources;
  connectorCount: number;
}

// Union type for folders and documents in hierarchy tables
export type HierarchyItem =
  | { type: "folder"; data: HierarchyNodeSummary }
  | { type: "document"; data: DocumentSummary };

// Props for hierarchy breadcrumb navigation
export interface HierarchyBreadcrumbProps {
  source: ValidSources;
  path: HierarchyNodeSummary[];
  onNavigateToRoot: () => void;
  onNavigateToNode: (node: HierarchyNodeSummary, index: number) => void;
}
