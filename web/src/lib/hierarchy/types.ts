import { ValidSources } from "@/lib/types";

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
  last_modified: string | null;
  last_synced: string | null;
  document_id: string;
}

export interface HierarchyNodeDocumentsRequest {
  parent_hierarchy_node_id: number;
  cursor?: DocumentPageCursor | null;
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
}

// Connected source type for display
export interface ConnectedSource {
  source: ValidSources;
  connectorCount: number;
}
