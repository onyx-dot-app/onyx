import { DateRangePickerValue } from "@tremor/react";
import { Tag, ValidSources } from "../types";
import { Persona } from "@/app/admin/assistants/interfaces";

export const FlowType = {
  SEARCH: "search",
  QUESTION_ANSWER: "question-answer",
};
export type FlowType = (typeof FlowType)[keyof typeof FlowType];
export const SearchType = {
  SEMANTIC: "semantic",
  KEYWORD: "keyword",
  AUTOMATIC: "automatic",
};
export type SearchType = (typeof SearchType)[keyof typeof SearchType];

export interface AnswerPiecePacket {
  answer_piece: string;
}

export interface ErrorMessagePacket {
  error: string;
}

export interface Quote {
  quote: string;
  document_id: string;
  link: string | null;
  source_type: ValidSources;
  blurb: string;
  semantic_identifier: string;
}

export interface QuotesInfoPacket {
  quotes: Quote[];
}

export interface DanswerDocument {
  document_id: string;
  link: string;
  source_type: ValidSources;
  blurb: string;
  semantic_identifier: string | null;
  boost: number;
  hidden: boolean;
  score: number;
  match_highlights: string[];
  metadata: { [key: string]: string };
  updated_at: string | null;
  db_doc_id?: number;
}

export interface DocumentInfoPacket {
  top_documents: DanswerDocument[];
  predicted_flow: FlowType | null;
  predicted_search: SearchType | null;
  time_cutoff: string | null;
  favor_recent: boolean;
}

export interface LLMRelevanceFilterPacket {
  relevant_chunk_indices: number[];
}

export interface SearchResponse {
  suggestedSearchType: SearchType | null;
  suggestedFlowType: FlowType | null;
  answer: string | null;
  quotes: Quote[] | null;
  documents: DanswerDocument[] | null;
  selectedDocIndices: number[] | null;
  error: string | null;
  messageId: number | null;
}

export enum SourceCategory {
  AppConnection = "Connect to Apps",
  ImportedKnowledge = "Import Knowledge",
}

export interface SourceMetadata {
  icon: React.FC<{ size?: number; className?: string }>;
  displayName: string;
  category: SourceCategory;
  shortDescription?: string;
  internalName: ValidSources;
  adminUrl: string;
}

export interface SearchDefaultOverrides {
  forceDisplayQA: boolean;
  offset: number;
}

export interface Filters {
  source_type: string[] | null;
  document_set: string[] | null;
  time_cutoff: Date | null;
}

export interface SearchRequestArgs {
  query: string;
  sources: SourceMetadata[];
  documentSets: string[];
  timeRange: DateRangePickerValue | null;
  tags: Tag[];
  persona: Persona;
  updateCurrentAnswer: (val: string) => void;
  updateQuotes: (quotes: Quote[]) => void;
  updateDocs: (documents: DanswerDocument[]) => void;
  updateSelectedDocIndices: (docIndices: number[]) => void;
  updateSuggestedSearchType: (searchType: SearchType) => void;
  updateSuggestedFlowType: (flowType: FlowType) => void;
  updateError: (error: string) => void;
  updateMessageId: (messageId: number) => void;
  selectedSearchType: SearchType | null;
}

export interface SearchRequestOverrides {
  searchType?: SearchType;
  offset?: number;
}

export interface ValidQuestionResponse {
  answerable: boolean | null;
  reasoning: string | null;
  error: string | null;
}
