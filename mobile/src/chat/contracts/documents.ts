// Search documents attached to response text and tool results.

export interface SearchDoc {
  document_id: string;
  semantic_identifier: string;
  link: string | null;
  blurb: string;
  source_type: string;
  score: number | null;
  updated_at: string | null; // ISO-8601
  match_highlights: string[];
  metadata: Record<string, string | string[]>;
  is_internet: boolean;
  chunk_ind: number;
  boost: number;
  hidden: boolean;
  primary_owners: string[] | null;
  secondary_owners: string[] | null;
  is_relevant: boolean | null;
  relevance_explanation: string | null;
  file_id: string | null;
}

// The deduped, first-cite-ordered citation record (mirrors web's StreamingCitation). Distinct from
// the wire `CitationInfo` packet, which uses `citation_number` (not `citation_num`).
export interface StreamingCitation {
  citation_num: number;
  document_id: string;
}

// citation_number -> document_id
export type CitationMap = Record<number, string>;
