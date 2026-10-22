import { ValidSources } from "@/lib/types";
import {
  HierarchyNodesResponse,
  HierarchyNodeDocumentsRequest,
  HierarchyNodeDocumentsResponse,
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
  source: ValidSources,
  ltiCourseId?: string | null
): Promise<HierarchyNodesResponse> {
  const prefix = ltiCourseId
    ? `/api/auth/lti/course/${encodeURIComponent(
        ltiCourseId
      )}/knowledge/hierarchy-nodes`
    : HIERARCHY_NODES_PREFIX;
  const response = await fetch(
    `${prefix}?source=${encodeURIComponent(source)}`
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
  request: HierarchyNodeDocumentsRequest,
  ltiCourseId?: string | null
): Promise<HierarchyNodeDocumentsResponse> {
  const prefix = ltiCourseId
    ? `/api/auth/lti/course/${encodeURIComponent(
        ltiCourseId
      )}/knowledge/hierarchy-nodes`
    : HIERARCHY_NODES_PREFIX;
  const response = await fetch(`${prefix}/documents`, {
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
