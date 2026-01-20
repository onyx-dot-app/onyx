/**
 * API Types - Mirror backend streaming_models.py packet structure
 */

export interface Packet {
  placement?: Record<string, any>;
  obj: PacketType;
}

export type PacketType =
  | MessageResponseIDInfo
  | MessageStart
  | MessageDelta
  | CitationInfo
  | SearchToolStart
  | SearchToolQueriesDelta
  | SearchToolDocumentsDelta
  | OpenUrlStart
  | OpenUrlUrls
  | OpenUrlDocuments
  | ImageGenerationStart
  | ImageGenerationHeartbeat
  | PythonToolStart
  | PythonToolDelta
  | CustomToolStart
  | ReasoningStart
  | ReasoningDelta
  | DeepResearchPlanStart
  | ResearchAgentStart
  | IntermediateReportStart
  | Stop
  | OverallStop
  | ErrorPacket;

export interface MessageResponseIDInfo {
  type?: "message_response_id_info"; // Optional for backend compatibility
  user_message_id: number | null;
  reserved_assistant_message_id: number;
}

export interface MessageStart {
  type: "message_start";
}

export interface MessageDelta {
  type: "message_delta";
  content: string;
}

export interface CitationInfo {
  type: "citation_info";
  citations: Citation[];
}

export interface Citation {
  document_id: string;
  semantic_identifier: string;
  title?: string;
  link?: string;
}

export interface SearchToolStart {
  type: "search_tool_start";
  is_internet_search?: boolean;
}

export interface SearchToolQueriesDelta {
  type: "search_tool_queries_delta";
  queries: string[];
}

export interface SearchToolDocumentsDelta {
  type: "search_tool_documents_delta";
  documents: SearchDocument[];
}

export interface SearchDocument {
  document_id: string;
  semantic_identifier: string;
  title: string;
  link?: string;
}

export interface OpenUrlStart {
  type: "open_url_start";
}

export interface OpenUrlUrls {
  type: "open_url_urls";
  urls: string[];
}

export interface OpenUrlDocuments {
  type: "open_url_documents";
  documents: SearchDocument[];
}

export interface ImageGenerationStart {
  type: "image_generation_start";
}

export interface ImageGenerationHeartbeat {
  type: "image_generation_heartbeat";
}

export interface PythonToolStart {
  type: "python_tool_start";
}

export interface PythonToolDelta {
  type: "python_tool_delta";
  code?: string;
}

export interface CustomToolStart {
  type: "custom_tool_start";
}

export interface ReasoningStart {
  type: "reasoning_start";
}

export interface ReasoningDelta {
  type: "reasoning_delta";
  reasoning: string;
}

export interface DeepResearchPlanStart {
  type: "deep_research_plan_start";
}

export interface ResearchAgentStart {
  type: "research_agent_start";
}

export interface IntermediateReportStart {
  type: "intermediate_report_start";
}

export interface Stop {
  type: "stop";
}

export interface OverallStop {
  type: "overall_stop";
}

export interface ErrorPacket {
  type: "error";
  exception: string;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: number;
  isStreaming?: boolean;
  citations?: Citation[];
}

export interface ChatSession {
  id: string;
  created_at: string;
  updated_at: string;
  messages: Message[];
}

export interface SendMessageRequest {
  message: string;
  chat_session_id?: string;
  parent_message_id?: number | null;
  origin?: string;
  include_citations?: boolean;
}

export interface CreateSessionRequest {
  persona_id?: number;
}

export interface CreateSessionResponse {
  chat_session_id: string;
}
