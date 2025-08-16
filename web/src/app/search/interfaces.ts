import { ValidSources } from "@/lib/types";

export interface SavedSearchDoc {
  document_id: string;
  chunk_ind: number;
  semantic_identifier: string;
  link: string | null;
  blurb: string;
  source_type: ValidSources;
  boost: number;
  hidden: boolean;
  metadata: { [key: string]: string | string[] };
  score: number;
  match_highlights: string[];
  updated_at: string | null;
  primary_owners: string[] | null;
  secondary_owners: string[] | null;
  is_internet: boolean;
  db_doc_id: number;
  is_relevant?: boolean | null;
  relevance_explanation?: string | null;
  tags?: string[] | null;
}
