import { OnyxDocument } from "@/lib/search/interfaces";

// Base interface for all streaming objects
interface BaseObj {
  type: string;
}

export enum PacketType {
  MESSAGE_START = "message_start",
  MESSAGE_DELTA = "message_delta",
  MESSAGE_END = "message_end",

  STOP = "stop",
  SECTION_END = "section_end",
  TOP_LEVEL_BRANCHING = "top_level_branching",
  ERROR = "error",

  // Specific tool packets
  SEARCH_TOOL_START = "search_tool_start",
  SEARCH_TOOL_QUERIES_DELTA = "search_tool_queries_delta",
  SEARCH_TOOL_DOCUMENTS_DELTA = "search_tool_documents_delta",
  IMAGE_GENERATION_TOOL_START = "image_generation_start",
  IMAGE_GENERATION_TOOL_DELTA = "image_generation_final",
  PYTHON_TOOL_START = "python_tool_start",
  PYTHON_TOOL_DELTA = "python_tool_delta",
  FETCH_TOOL_START = "open_url_start",
  FETCH_TOOL_URLS = "open_url_urls",
  FETCH_TOOL_DOCUMENTS = "open_url_documents",

  // Custom tool packets
  CUSTOM_TOOL_START = "custom_tool_start",
  CUSTOM_TOOL_DELTA = "custom_tool_delta",

  // Reasoning packets
  REASONING_START = "reasoning_start",
  REASONING_DELTA = "reasoning_delta",
  REASONING_DONE = "reasoning_done",

  // Citation packets
  CITATION_START = "citation_start",
  CITATION_END = "citation_end",
  // Backend sends individual citation_info packets during streaming
  CITATION_INFO = "citation_info",

  // Deep Research packets
  DEEP_RESEARCH_PLAN_START = "deep_research_plan_start",
  DEEP_RESEARCH_PLAN_DELTA = "deep_research_plan_delta",
  RESEARCH_AGENT_START = "research_agent_start",
  INTERMEDIATE_REPORT_START = "intermediate_report_start",
  INTERMEDIATE_REPORT_DELTA = "intermediate_report_delta",
  INTERMEDIATE_REPORT_CITED_DOCS = "intermediate_report_cited_docs",
}

// Basic Message Packets
export interface MessageStart extends BaseObj {
  id: string;
  type: "message_start";
  content: string;

  final_documents: OnyxDocument[] | null;
}

export interface MessageDelta extends BaseObj {
  content: string;
  type: "message_delta";
}

export interface MessageEnd extends BaseObj {
  type: "message_end";
}

// Control Packets
export enum StopReason {
  FINISHED = "finished",
  USER_CANCELLED = "user_cancelled",
}

export interface Stop extends BaseObj {
  type: "stop";
  stop_reason?: StopReason;
}

export interface SectionEnd extends BaseObj {
  type: "section_end";
}

export interface TopLevelBranching extends BaseObj {
  type: "top_level_branching";
  num_parallel_branches: number;
}

export interface PacketError extends BaseObj {
  type: "error";
  message?: string;
}

// Specific tool packets
export interface SearchToolStart extends BaseObj {
  type: "search_tool_start";
  is_internet_search?: boolean;
}

export interface SearchToolQueriesDelta extends BaseObj {
  type: "search_tool_queries_delta";
  queries: string[];
}

export interface SearchToolDocumentsDelta extends BaseObj {
  type: "search_tool_documents_delta";
  documents: OnyxDocument[];
}

export type ImageShape = "square" | "landscape" | "portrait";

interface GeneratedImage {
  file_id: string;
  url: string;
  revised_prompt: string;
  shape?: ImageShape;
}

export interface ImageGenerationToolStart extends BaseObj {
  type: "image_generation_start";
}

export interface ImageGenerationToolDelta extends BaseObj {
  type: "image_generation_final";
  images: GeneratedImage[];
}

export interface PythonToolStart extends BaseObj {
  type: "python_tool_start";
  code: string;
}

export interface PythonToolDelta extends BaseObj {
  type: "python_tool_delta";
  stdout: string;
  stderr: string;
  file_ids: string[];
}

export interface FetchToolStart extends BaseObj {
  type: "open_url_start";
}

export interface FetchToolUrls extends BaseObj {
  type: "open_url_urls";
  urls: string[];
}

export interface FetchToolDocuments extends BaseObj {
  type: "open_url_documents";
  documents: OnyxDocument[];
}

// Custom Tool Packets
export interface CustomToolStart extends BaseObj {
  type: "custom_tool_start";
  tool_name: string;
}

export interface CustomToolDelta extends BaseObj {
  type: "custom_tool_delta";
  tool_name: string;
  response_type: string;
  data?: any;
  file_ids?: string[] | null;
}

// Reasoning Packets
export interface ReasoningStart extends BaseObj {
  type: "reasoning_start";
}

export interface ReasoningDelta extends BaseObj {
  type: "reasoning_delta";
  reasoning: string;
}

export interface ReasoningDone extends BaseObj {
  type: "reasoning_done";
}

// Citation Packets
export interface StreamingCitation {
  citation_num: number;
  document_id: string;
}

export interface CitationStart extends BaseObj {
  type: "citation_start";
}

// Individual citation info packet (sent during streaming from backend)
export interface CitationInfo extends BaseObj {
  type: "citation_info";
  citation_number: number;
  document_id: string;
}

// Deep Research Plan Packets
export interface DeepResearchPlanStart extends BaseObj {
  type: "deep_research_plan_start";
}

export interface DeepResearchPlanDelta extends BaseObj {
  type: "deep_research_plan_delta";
  content: string;
}

export interface ResearchAgentStart extends BaseObj {
  type: "research_agent_start";
  research_task: string;
}

export interface IntermediateReportStart extends BaseObj {
  type: "intermediate_report_start";
}

export interface IntermediateReportDelta extends BaseObj {
  type: "intermediate_report_delta";
  content: string;
}

export interface IntermediateReportCitedDocs extends BaseObj {
  type: "intermediate_report_cited_docs";
  cited_docs: OnyxDocument[] | null;
}

export type ChatObj = MessageStart | MessageDelta | MessageEnd;

export type StopObj = Stop;

export type SectionEndObj = SectionEnd;

export type TopLevelBranchingObj = TopLevelBranching;

export type PacketErrorObj = PacketError;

// Specific tool objects
export type SearchToolObj =
  | SearchToolStart
  | SearchToolQueriesDelta
  | SearchToolDocumentsDelta
  | SectionEnd
  | PacketError;
export type ImageGenerationToolObj =
  | ImageGenerationToolStart
  | ImageGenerationToolDelta
  | SectionEnd
  | PacketError;
export type PythonToolObj =
  | PythonToolStart
  | PythonToolDelta
  | SectionEnd
  | PacketError;
export type FetchToolObj =
  | FetchToolStart
  | FetchToolUrls
  | FetchToolDocuments
  | SectionEnd
  | PacketError;
export type CustomToolObj =
  | CustomToolStart
  | CustomToolDelta
  | SectionEnd
  | PacketError;
export type NewToolObj =
  | SearchToolObj
  | ImageGenerationToolObj
  | PythonToolObj
  | FetchToolObj
  | CustomToolObj;

export type ReasoningObj =
  | ReasoningStart
  | ReasoningDelta
  | ReasoningDone
  | SectionEnd
  | PacketError;

export type CitationObj =
  | CitationStart
  | CitationInfo
  | SectionEnd
  | PacketError;

export type DeepResearchPlanObj =
  | DeepResearchPlanStart
  | DeepResearchPlanDelta
  | SectionEnd;

export type ResearchAgentObj =
  | ResearchAgentStart
  | IntermediateReportStart
  | IntermediateReportDelta
  | IntermediateReportCitedDocs
  | SectionEnd;

// Union type for all possible streaming objects
export type ObjTypes =
  | ChatObj
  | NewToolObj
  | ReasoningObj
  | StopObj
  | SectionEndObj
  | TopLevelBranchingObj
  | CitationObj
  | DeepResearchPlanObj
  | ResearchAgentObj
  | PacketErrorObj
  | CitationObj;

// Placement interface for packet positioning
export interface Placement {
  turn_index: number;
  tab_index?: number; // For parallel tool calls - tools with same turn_index but different tab_index run in parallel
  sub_turn_index?: number | null;
}

// Packet wrapper for streaming objects
export interface Packet {
  placement: Placement;
  obj: ObjTypes;
}

export interface ChatPacket {
  placement: Placement;
  obj: ChatObj;
}

export interface StopPacket {
  placement: Placement;
  obj: StopObj;
}

export interface CitationPacket {
  placement: Placement;
  obj: CitationObj;
}

// New specific tool packet types
export interface SearchToolPacket {
  placement: Placement;
  obj: SearchToolObj;
}

export interface ImageGenerationToolPacket {
  placement: Placement;
  obj: ImageGenerationToolObj;
}

export interface PythonToolPacket {
  placement: Placement;
  obj: PythonToolObj;
}

export interface FetchToolPacket {
  placement: Placement;
  obj: FetchToolObj;
}

export interface CustomToolPacket {
  placement: Placement;
  obj: CustomToolObj;
}

export interface ReasoningPacket {
  placement: Placement;
  obj: ReasoningObj;
}

export interface SectionEndPacket {
  placement: Placement;
  obj: SectionEndObj;
}

export interface TopLevelBranchingPacket {
  placement: Placement;
  obj: TopLevelBranchingObj;
}

export interface DeepResearchPlanPacket {
  placement: Placement;
  obj: DeepResearchPlanObj;
}

export interface ResearchAgentPacket {
  placement: Placement;
  obj: ResearchAgentObj;
}
