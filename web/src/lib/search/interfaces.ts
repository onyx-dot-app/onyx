import { InputDateRangePickerValue } from "@opal/components";
import { Tag, ValidSources } from "../types";
import { Agent } from "@/lib/agents/types";

const FlowType = {
  SEARCH: "search",
  QUESTION_ANSWER: "question-answer",
};
type FlowType = (typeof FlowType)[keyof typeof FlowType];
const SearchType = {
  SEMANTIC: "semantic",
  KEYWORD: "keyword",
  AUTOMATIC: "automatic",
  INTERNET: "internet",
};
type SearchType = (typeof SearchType)[keyof typeof SearchType];

interface ToolResponse {
  id?: string | null;
  response?: any;
}
interface ExtendedToolResponse extends ToolResponse {
  level: number;
  level_question_num: number;
}

export enum StreamStopReason {
  CONTEXT_LENGTH = "CONTEXT_LENGTH",
  CANCELLED = "CANCELLED",
}

export interface StreamStopInfo {
  stop_reason: StreamStopReason;
  level?: number;
  level_question_num?: number;
  stream_type?: "sub_answer" | "sub_questions" | "main_answer";
}

interface ErrorMessagePacket {
  error: string;
}

interface Quote {
  quote: string;
  document_id: string;
  link: string | null;
  source_type: ValidSources;
  blurb: string;
  semantic_identifier: string;
}

interface QuotesInfoPacket {
  quotes: Quote[];
}
export interface MinimalOnyxDocument {
  document_id: string;
  semantic_identifier: string | null;
}

export interface OnyxDocument extends MinimalOnyxDocument {
  link: string;
  source_type: ValidSources;
  blurb: string;
  boost: number;
  hidden: boolean;
  score: number;
  chunk_ind: number;
  match_highlights: string[];
  metadata: { [key: string]: string };
  updated_at: string | null;
  db_doc_id?: number;
  is_internet: boolean;
  validationState?: null | "good" | "bad";
}

interface LoadedOnyxDocument extends OnyxDocument {
  icon: React.FC<{ size?: number; className?: string }>;
}

export interface SearchOnyxDocument extends OnyxDocument {
  is_relevant: boolean;
  relevance_explanation: string;
}

interface FilteredOnyxDocument extends OnyxDocument {
  included: boolean;
}
export interface DocumentInfoPacket {
  top_documents: OnyxDocument[];
  predicted_flow: FlowType | null;
  predicted_search: SearchType | null;
  time_cutoff: string | null;
  favor_recent: boolean;
}

interface DocumentRelevance {
  relevant: boolean;
  content: string;
}

interface Relevance {
  [url: string]: DocumentRelevance;
}

interface RelevanceChunk {
  relevance_summaries: Relevance;
}

interface SearchResponse {
  suggestedSearchType: SearchType | null;
  suggestedFlowType: FlowType | null;
  answer: string | null;
  quotes: Quote[] | null;
  documents: SearchOnyxDocument[] | null;
  selectedDocIndices: number[] | null;
  error: string | null;
  messageId: number | null;
  additional_relevance?: Relevance;
}

export enum SourceCategory {
  Wiki = "Knowledge Base & Wikis",
  Storage = "Cloud Storage",
  TicketingAndTaskManagement = "Ticketing & Task Management",
  Messaging = "Messaging",
  Sales = "Sales",
  CodeRepository = "Code Repository",
  Other = "Others",
}

export interface SourceMetadata {
  icon: React.FC<{ size?: number; className?: string }>;
  displayName: string;
  category: SourceCategory;
  shortDescription?: string;
  internalName: ValidSources;
  adminUrl: string;
  isPopular?: boolean;
  oauthSupported?: boolean;
  federated?: boolean;
  federatedTooltip?: string;
  uniqueKey?: string;
  // For federated connectors, this stores the base source type for the icon
  baseSourceType?: ValidSources;
  // For connectors that are always available (don't need connection setup)
  // e.g., User Library (CraftFile) where users just upload files
  alwaysConnected?: boolean;
  // Custom description to show instead of status (e.g., "Manage your uploaded files")
  customDescription?: string;
}

interface SearchDefaultOverrides {
  forceDisplayQA: boolean;
  offset: number;
}

interface SearchRequestArgs {
  query: string;
  agentic?: boolean;
  sources: SourceMetadata[];
  documentSets: string[];
  timeRange: InputDateRangePickerValue | null;
  tags: Tag[];
  persona: Agent;
  updateDocumentRelevance: (relevance: any) => void;
  updateCurrentAnswer: (val: string) => void;
  updateQuotes: (quotes: Quote[]) => void;
  updateDocs: (documents: OnyxDocument[]) => void;
  updateSelectedDocIndices: (docIndices: number[]) => void;
  updateSuggestedSearchType: (searchType: SearchType) => void;
  updateSuggestedFlowType: (flowType: FlowType) => void;
  updateError: (error: string) => void;
  updateMessageAndThreadId: (
    messageId: number,
    chat_session_id: string
  ) => void;
  finishedSearching: () => void;
  updateComments: (comments: any) => void;
  selectedSearchType: SearchType | null;
}

interface SearchRequestOverrides {
  searchType?: SearchType;
  offset?: number;
  overrideMessage?: string;
  agentic?: boolean;
}

interface ValidQuestionResponse {
  reasoning: string | null;
  error: string | null;
}

// ============================================================================
// Classification API
// ============================================================================

/**
 * Request to classify a query as search or chat flow
 * POST /api/search/search-flow-classification
 */
export interface SearchFlowClassificationRequest {
  user_query: string;
}

/**
 * Response from query classification
 */
export interface SearchFlowClassificationResponse {
  is_search_flow: boolean;
}

// ============================================================================
// Search API (Unified Search + Chat)
// ============================================================================

/**
 * Base filters for search queries
 * Matches backend/onyx/context/search/models.py BaseFilters
 */
export interface BaseFilters {
  source_type?: ValidSources[] | null;
  document_set?: string[] | null;
  // Bounds are ISO date strings.
  updated_at_range?: { start: string | null; end: string | null } | null;
  tags?: Array<{ tag_key: string; tag_value: string }> | null;
}

/**
 * Request to perform a document search
 * POST /api/search/send-search-message
 */
export interface SendSearchQueryRequest {
  search_query: string;
  filters?: BaseFilters | null;
  num_docs_fed_to_llm_selection?: number | null;
  run_query_expansion?: boolean;
  num_hits?: number; // default 30
  include_content?: boolean;
  stream?: boolean;
}

/**
 * Search document with optional content
 * Matches backend SearchDocWithContent
 */
export interface SearchDocWithContent {
  document_id: string;
  chunk_ind: number;
  semantic_identifier: string;
  link: string | null;
  blurb: string;
  source_type: ValidSources;
  boost: number;
  hidden: boolean;
  metadata: Record<string, string | string[]>;
  score: number | null;
  is_relevant?: boolean | null;
  relevance_explanation?: string | null;
  match_highlights: string[];
  updated_at: string | null; // ISO date string
  primary_owners?: string[] | null;
  secondary_owners?: string[] | null;
  is_internet: boolean;
  content?: string | null;
}

/**
 * Full response from a search query (non-streaming)
 */
export interface SearchFullResponse {
  all_executed_queries: string[];
  search_docs: SearchDocWithContent[];
  doc_selection_reasoning?: string | null;
  llm_selected_doc_ids?: string[] | null;
  error?: string | null;
}

// ============================================================================
// Search History API
// ============================================================================

/**
 * Single search query in history
 */
interface SearchQueryResponse {
  query: string;
  query_expansions: string[] | null;
  created_at: string; // ISO date string
}

/**
 * Response from search history endpoint
 * GET /api/search/search-history
 */
export interface SearchHistoryResponse {
  search_queries: SearchQueryResponse[];
}

// ============================================================================
// Streaming Packets (for stream=true)
// ============================================================================

interface SearchDocsPacket {
  type: "search_docs";
  search_docs: SearchDocWithContent[];
}

interface SearchErrorPacket {
  type: "search_error";
  error: string;
}

interface LLMSelectedDocsPacket {
  type: "llm_selected_docs";
  llm_selected_doc_ids: string[] | null;
}

interface QueryExpansionsPacket {
  type: "query_expansions";
  executed_queries: string[];
}

interface DocSelectionReasoningPacket {
  type: "doc_selection_reasoning";
  reasoning: string;
}

type SearchStreamPacket =
  | SearchDocsPacket
  | SearchErrorPacket
  | LLMSelectedDocsPacket
  | QueryExpansionsPacket
  | DocSelectionReasoningPacket;
