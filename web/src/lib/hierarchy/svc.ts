import { ValidSources } from "@/lib/types";
import {
  HierarchyNodesResponse,
  HierarchyNodeDocumentsRequest,
  HierarchyNodeDocumentsResponse,
} from "./interfaces";

const HIERARCHY_NODES_PREFIX = "/api/hierarchy-nodes";

export async function fetchHierarchyNodes(
  source: ValidSources
): Promise<HierarchyNodesResponse> {
  const response = await fetch(
    `${HIERARCHY_NODES_PREFIX}?source=${encodeURIComponent(source)}`
  );

  if (!response.ok) {
    throw new Error(`Failed to fetch hierarchy nodes: ${response.statusText}`);
  }

  return response.json();
}

export async function fetchHierarchyNodeDocuments(
  request: HierarchyNodeDocumentsRequest
): Promise<HierarchyNodeDocumentsResponse> {
  const response = await fetch(`${HIERARCHY_NODES_PREFIX}/documents`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    throw new Error(
      `Failed to fetch hierarchy node documents: ${response.statusText}`
    );
  }

  return response.json();
}
