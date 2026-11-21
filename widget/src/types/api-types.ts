/**
 * API Types - Mirror backend streaming_models.py packet structure
 */

export interface Packet {
  placement?: Record<string, any>;
  obj: PacketType;
}

/** A resumed stream's position after the packets before it. */
export interface StreamCursor {
  stream_id: number;
  next_cursor: number;
  replay_complete: boolean;
}

export type PacketType =
  | MessageResponseIDInfo
  | UserMessagePacket
  | ReplayEnd
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
  | ToolApprovalRequest
  | ToolApprovalResolved
  | ToolQuestionRequest
  | ToolQuestionResolved
  | Stop
  | OverallStop
  | ErrorPacket;

export interface MessageResponseIDInfo {
  type?: "message_response_id_info"; // Optional for backend compatibility
  user_message_id: number | null;
  reserved_assistant_message_id: number;
}

/** A question the turn accepted; `id` is not the saved message id. */
export interface UserMessagePacket {
  type: "user_message";
  id: string;
  message: string;
}

/**
 * Ends the replayed prefix of a stream that continues a suspended response;
 * the packets after it are live.
 */
export interface ReplayEnd {
  type: "replay_end";
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
  citation_number: number;
  document_id: string;
}

export interface ResolvedCitation {
  citation_number: number;
  document_id: string;
  semantic_identifier?: string;
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

/** A tool call waits for the user's decision. */
export interface ToolApprovalRequest {
  type: "tool_approval_request";
  approval_id: string;
  tool_call_id: string;
  tool_name: string;
  display_name: string;
  arguments: Record<string, unknown>;
  // The subagent that asks; null or absent for the root agent's own requests
  agent_name?: string | null;
}

export interface ToolApprovalResolved {
  type: "tool_approval_resolved";
  approval_id: string;
  // approved | approved_for_chat | rejected | disabled | cancelled;
  // anything else is ignored
  outcome: string;
}

export interface ToolQuestionOption {
  label: string;
  // What the choice means or changes
  description: string;
}

export interface ToolQuestion {
  id: string;
  // A short label, at most 12 characters
  header: string;
  question: string;
  options: ToolQuestionOption[];
}

/** The user's answer to one question: one of its options, a note, or both. */
export interface ToolQuestionAnswer {
  question_id: string;
  option_label?: string | null;
  user_note?: string | null;
}

/** A question call of the root agent waits for the user's answers. */
export interface ToolQuestionRequest {
  type: "tool_question_request";
  question_request_id: string;
  tool_call_id: string;
  questions: ToolQuestion[];
}

/**
 * How a question call ended: answered on its card (`answers`), by a message
 * that the user typed in the chat (`message`), or cancelled.
 */
export interface ToolQuestionResolved {
  type: "tool_question_resolved";
  question_request_id: string;
  // answered | cancelled; anything else is ignored
  outcome: string;
  answered_via?: "card" | "message" | null;
  answers?: ToolQuestionAnswer[] | null;
  message?: string | null;
}

/** A running stream and the responses it writes. */
export interface ChatStream {
  stream_id: number;
  response_ids: number[];
}

export interface ApprovalDecisionResponse {
  decision: "APPROVED" | "REJECTED";
  // "POLICY": the action policy disabled the tool, so the approval rejected it.
  decided_via: string;
  // The stream that continues the response; null while other requests still
  // wait, or for a background agent's request, which continues without one
  continuation: ChatStream | null;
}

/** The body of a question request's answers: card answers or a typed message. */
export type QuestionAnswersRequest =
  | { answers: ToolQuestionAnswer[] }
  | { message: string };

export interface QuestionAnswersResponse {
  // The stream that continues the response; null while other requests or
  // questions of the response still wait
  continuation: ChatStream | null;
}

/** The stream's last packet. */
export interface Stop {
  type: "stop";
  // "awaiting_user": the response waits for the user's decisions or answers
  // and continues on a new stream after them
  stop_reason?: string | null;
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
  citations?: ResolvedCitation[];
}

export interface ChatSession {
  id: string;
  created_at: string;
  updated_at: string;
  messages: Message[];
}

/** The fields of `/chat/get-chat-session` that the widget reads. */
export interface ChatSessionDetail {
  messages: {
    message_id: number;
    message_type: string;
    // The question an assistant message answers
    parent_message?: number | null;
    // The child on the selected branch; the load returns every branch
    latest_child_message?: number | null;
  }[];
  // One replay packet list for each assistant message, in message order
  packets: Packet[][];
  // The status's `approvals_version` for the requests this load shows
  approvals_version?: string;
}

/** The fields of `/chat/chat-session/{id}/status` that the widget reads. */
export interface ChatSessionStatus {
  is_processing: boolean;
  // Background agents run, their queued work waits, or a decided agent
  // waits to resume; an agent that waits for a decision does not count
  has_active_subagents: boolean;
  // Queued input or unread root results can start a turn; a paused queue
  // cannot
  has_startable_input: boolean;
  // The newest response on the selected branch
  latest_response_id: number | null;
  current_stream: ChatStream | null;
  // Changes when a request of the chat opens, is decided or is removed
  approvals_version: string | null;
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
