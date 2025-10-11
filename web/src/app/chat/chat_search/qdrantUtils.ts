import { QdrantSearchRequest, QdrantSearchResponse } from "./qdrantInterfaces";

const API_BASE_URL = "/api";

export async function searchQdrantDocuments(
  params: QdrantSearchRequest
): Promise<QdrantSearchResponse> {
  const queryParams = new URLSearchParams();
  queryParams.append("query", params.query);

  if (params.limit) {
    queryParams.append("limit", params.limit.toString());
  }

  const queryString = `?${queryParams.toString()}`;

  const response = await fetch(`${API_BASE_URL}/qdrant/search${queryString}`, {
    method: "GET",
    headers: {
      "Content-Type": "application/json",
    },
    signal: params.signal,
  });

  if (!response.ok) {
    throw new Error(
      `Failed to search Qdrant documents: ${response.statusText}`
    );
  }

  return response.json();
}
