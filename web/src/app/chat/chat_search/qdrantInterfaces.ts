export interface QdrantSearchResult {
  document_id: string;
  content: string;
  filename: string | null;
  source_type: string | null;
  score: number;
  metadata: Record<string, any> | null;
}

export interface QdrantSearchResponse {
  results: QdrantSearchResult[];
  query: string;
  total_results: number;
}

export interface QdrantSearchRequest {
  query: string;
  limit?: number;
  signal?: AbortSignal;
}
