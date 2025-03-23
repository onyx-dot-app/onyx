import { handleSSEStream } from "@/lib/search/streamingUtils";
import {
  OnyxDocument,
  SourceMetadata,
  AnswerPiecePacket,
  DocumentInfoPacket,
} from "@/lib/search/interfaces";
import { Persona } from "@/app/admin/assistants/interfaces";
import { buildFilters } from "@/lib/search/utils";
import { Tag } from "@/lib/types";
import { DateRangePickerValue } from "@/app/ee/admin/performance/DateRangeSelector";
import { StreamingError } from "@/app/chat/interfaces";

export interface SearchStreamResponse {
  answer: string | null;
  documents: OnyxDocument[];
  error: string | null;
}

// Define interface matching FastSearchResult
interface FastSearchResult {
  document_id: string;
  chunk_id: number;
  content: string;
  source_links: string[];
  score?: number;
  metadata?: {
    source_type?: string;
    semantic_identifier?: string;
    boost?: number;
    hidden?: boolean;
    updated_at?: string;
    primary_owners?: string[];
    secondary_owners?: string[];
    [key: string]: any;
  };
}

export async function* streamSearchWithCitation({
  query,
  persona,
  sources,
  documentSets,
  timeRange,
  tags,
}: {
  query: string;
  persona: Persona;
  sources: SourceMetadata[];
  documentSets: string[];
  timeRange: DateRangePickerValue | null;
  tags: Tag[];
}): AsyncGenerator<SearchStreamResponse> {
  const filters = buildFilters(sources, documentSets, timeRange, tags);

  // Use the fast-search endpoint instead
  const response = await fetch("/api/query/fast-search", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      query: query,
      filters: filters,
      max_results: 300, // Use the default max results for fast search
    }),
  });

  if (!response.ok) {
    const errorText = await response.text();
    yield {
      answer: null,
      documents: [],
      error: `Error: ${response.status} - ${errorText}`,
    };
    return;
  }

  // Since fast-search is not streaming, we need to process the complete response
  const searchResults = await response.json();
  console.log("searchResults", searchResults);

  // Convert results to OnyxDocument format
  try {
    const documents: OnyxDocument[] = searchResults.results;

    console.log("documents", documents);

    // First yield just the documents to maintain similar streaming behavior
    yield {
      answer: null,
      documents,
      error: null,
    };

    // Final yield with completed results
    yield {
      answer: null,
      documents,
      error: null,
    };
  } catch (error) {
    console.error("Error in streamSearchWithCitation", error);
    yield {
      answer: null,
      documents: [],
      error: `Error: ${error}`,
    };
  }
}
