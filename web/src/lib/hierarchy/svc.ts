import { ValidSources } from "@/lib/types";
import {
  HierarchyNodesResponse,
  HierarchyNodeDocumentsRequest,
  HierarchyNodeDocumentsResponse,
  HierarchyNodeSearchResponse,
} from "./interfaces";

const HIERARCHY_NODES_PREFIX = "/api/hierarchy-nodes";

async function extractErrorDetail(
  response: Response,
  fallback: string
): Promise<string> {
  try {
    const body = await response.json();
    if (body.detail) return body.detail;
  } catch {
    // JSON parsing failed — fall through to fallback
  }
  return fallback;
}

export async function fetchHierarchyNodes(
  source: ValidSources
): Promise<HierarchyNodesResponse> {
  const response = await fetch(
    `${HIERARCHY_NODES_PREFIX}?source=${encodeURIComponent(source)}`
  );

  if (!response.ok) {
    const detail = await extractErrorDetail(
      response,
      `Failed to fetch hierarchy nodes: ${response.statusText}`
    );
    throw new Error(detail);
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
    const detail = await extractErrorDetail(
      response,
      `Failed to fetch hierarchy node documents: ${response.statusText}`
    );
    throw new Error(detail);
  }

  return response.json();
}

export async function fetchHierarchyNodeSearch(
  query: string,
  options?: {
    sources?: ValidSources[];
    signal?: AbortSignal;
  }
): Promise<HierarchyNodeSearchResponse> {
  const params = new URLSearchParams({ query });
  options?.sources?.forEach((s) => params.append("source", s));
  const response = await fetch(
    `${HIERARCHY_NODES_PREFIX}/search?${params.toString()}`,
    { signal: options?.signal }
  );

  if (!response.ok) {
    const detail = await extractErrorDetail(
      response,
      `Failed to search hierarchy nodes: ${response.statusText}`
    );
    throw new Error(detail);
  }

  return response.json();
}
