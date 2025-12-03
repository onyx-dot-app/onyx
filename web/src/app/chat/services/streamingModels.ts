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

  // Specific tool packets
  SEARCH_TOOL_START = "search_tool_start",
  SEARCH_TOOL_QUERIES_DELTA = "search_tool_queries_delta",
  SEARCH_TOOL_DOCUMENTS_DELTA = "search_tool_documents_delta",
  IMAGE_GENERATION_TOOL_START = "image_generation_start",
  IMAGE_GENERATION_TOOL_DELTA = "image_generation_final",
  PYTHON_TOOL_START = "python_tool_start",
  PYTHON_TOOL_DELTA = "python_tool_delta",
  FETCH_TOOL_START = "open_url_start",

  // Custom tool packets
  CUSTOM_TOOL_START = "custom_tool_start",
  CUSTOM_TOOL_DELTA = "custom_tool_delta",

  // Reasoning packets
  REASONING_START = "reasoning_start",
  REASONING_DELTA = "reasoning_delta",
  REASONING_DONE = "reasoning_done",

  // Citation packets
  CITATION_START = "citation_start",
  CITATION_DELTA = "citation_delta",
  CITATION_END = "citation_end",
  // Backend sends individual citation_info packets during streaming
  CITATION_INFO = "citation_info",
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
export interface Stop extends BaseObj {
  type: "stop";
}

export interface SectionEnd extends BaseObj {
  type: "section_end";
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

// Citation Packets
export interface StreamingCitation {
  citation_num: number;
  document_id: string;
}

export interface CitationStart extends BaseObj {
  type: "citation_start";
}

export interface CitationDelta extends BaseObj {
  type: "citation_delta";
  citations: StreamingCitation[];
}

// Individual citation info packet (sent during streaming from backend)
export interface CitationInfo extends BaseObj {
  type: "citation_info";
  citation_number: number;
  document_id: string;
}

export type ChatObj = MessageStart | MessageDelta | MessageEnd;

export type StopObj = Stop;

export type SectionEndObj = SectionEnd;

// Specific tool objects
export type SearchToolObj =
  | SearchToolStart
  | SearchToolQueriesDelta
  | SearchToolDocumentsDelta
  | SectionEnd;
export type ImageGenerationToolObj =
  | ImageGenerationToolStart
  | ImageGenerationToolDelta
  | SectionEnd;
export type PythonToolObj = PythonToolStart | PythonToolDelta | SectionEnd;
export type FetchToolObj = FetchToolStart | SectionEnd;
export type CustomToolObj = CustomToolStart | CustomToolDelta | SectionEnd;
export type NewToolObj =
  | SearchToolObj
  | ImageGenerationToolObj
  | PythonToolObj
  | FetchToolObj
  | CustomToolObj;

export type ReasoningObj = ReasoningStart | ReasoningDelta | SectionEnd;

export type CitationObj =
  | CitationStart
  | CitationDelta
  | CitationInfo
  | SectionEnd;

// Union type for all possible streaming objects
export type ObjTypes =
  | ChatObj
  | NewToolObj
  | ReasoningObj
  | StopObj
  | SectionEndObj
  | CitationObj;

// Packet wrapper for streaming objects
export interface Packet {
  turn_index: number;
  obj: ObjTypes;
}

export interface ChatPacket {
  turn_index: number;
  obj: ChatObj;
}

export interface StopPacket {
  turn_index: number;
  obj: StopObj;
}

export interface CitationPacket {
  turn_index: number;
  obj: CitationObj;
}

// New specific tool packet types
export interface SearchToolPacket {
  turn_index: number;
  obj: SearchToolObj;
}

export interface ImageGenerationToolPacket {
  turn_index: number;
  obj: ImageGenerationToolObj;
}

export interface PythonToolPacket {
  turn_index: number;
  obj: PythonToolObj;
}

export interface FetchToolPacket {
  turn_index: number;
  obj: FetchToolObj;
}

export interface CustomToolPacket {
  turn_index: number;
  obj: CustomToolObj;
}

export interface ReasoningPacket {
  turn_index: number;
  obj: ReasoningObj;
}

export interface SectionEndPacket {
  turn_index: number;
  obj: SectionEndObj;
}
