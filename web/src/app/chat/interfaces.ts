import {
  OnyxDocument,
  Filters,
  SearchOnyxDocument,
  StreamStopReason,
  SubQuestionPiece,
  SubQueryPiece,
  AgentAnswerPiece,
  SubQuestionSearchDoc,
  StreamStopInfo,
} from "@/lib/search/interfaces";

export enum RetrievalType {
  None = "none",
  Search = "search",
  SelectedDocs = "selectedDocs",
}

export enum ChatSessionSharedStatus {
  Private = "private",
  Public = "public",
}

// The number of messages to buffer on the client side.
export const BUFFER_COUNT = 35;

export interface RetrievalDetails {
  run_search: "always" | "never" | "auto";
  real_time: boolean;
  filters?: Filters;
  enable_auto_detect_filters?: boolean | null;
}

type CitationMap = { [key: string]: number };

export enum ChatFileType {
  IMAGE = "image",
  DOCUMENT = "document",
  PLAIN_TEXT = "plain_text",
  CSV = "csv",
}

export interface FileDescriptor {
  id: string;
  type: ChatFileType;
  name?: string | null;

  // FE only
  isUploading?: boolean;
}

export interface LLMRelevanceFilterPacket {
  relevant_chunk_indices: number[];
}

export interface ToolCallMetadata {
  tool_name: string;
  tool_args: Record<string, any>;
  tool_result?: Record<string, any>;
}

export interface ToolCallFinalResult {
  tool_name: string;
  tool_args: Record<string, any>;
  tool_result: Record<string, any>;
}

export interface ChatSession {
  id: string;
  name: string;
  persona_id: number;
  time_created: string;
  shared_status: ChatSessionSharedStatus;
  folder_id: number | null;
  current_alternate_model: string;
  current_temperature_override: number | null;
}

export interface SearchSession {
  search_session_id: string;
  documents: SearchOnyxDocument[];
  messages: BackendMessage[];
  description: string;
}

export interface Message {
  is_generating?: boolean;
  messageId: number;
  message: string;
  type: "user" | "assistant" | "system" | "error";
  retrievalType?: RetrievalType;
  query?: string | null;
  documents?: OnyxDocument[] | null;
  citations?: CitationMap;
  files: FileDescriptor[];
  toolCall: ToolCallMetadata | null;
  // for rebuilding the message tree
  parentMessageId: number | null;
  childrenMessageIds?: number[];
  latestChildMessageId?: number | null;
  alternateAssistantID?: number | null;
  stackTrace?: string | null;
  overridden_model?: string;
  stopReason?: StreamStopReason | null;
  sub_questions?: SubQuestionDetail[] | null;

  // Streaming only
  second_level_generating?: boolean;
  agentic_docs?: OnyxDocument[] | null;
  second_level_message?: string;
  second_level_subquestions?: SubQuestionDetail[] | null;
  isImprovement?: boolean | null;
  isStreamingQuestions?: boolean;
}

export interface BackendChatSession {
  chat_session_id: string;
  description: string;
  persona_id: number;
  persona_name: string;
  persona_icon_color: string | null;
  persona_icon_shape: number | null;
  messages: BackendMessage[];
  time_created: string;
  shared_status: ChatSessionSharedStatus;
  current_temperature_override: number | null;
  current_alternate_model?: string;
}

export interface BackendMessage {
  message_id: number;
  message_type: string;
  parent_message: number | null;
  latest_child_message: number | null;
  message: string;
  rephrased_query: string | null;
  context_docs: { top_documents: OnyxDocument[] } | null;
  time_sent: string;
  overridden_model: string;
  alternate_assistant_id: number | null;
  chat_session_id: string;
  citations: CitationMap | null;
  files: FileDescriptor[];
  tool_call: ToolCallFinalResult | null;

  sub_questions: SubQuestionDetail[];
  // Keeping existing properties
  comments: any;
  parentMessageId: number | null;
  refined_answer_improvement: boolean | null;
}

export interface MessageResponseIDInfo {
  user_message_id: number | null;
  reserved_assistant_message_id: number;
}

export interface DocumentsResponse {
  top_documents: OnyxDocument[];
  rephrased_query: string | null;
  level?: number | null;
  level_question_num?: number | null;
}

export interface FileChatDisplay {
  file_ids: string[];
}

export interface StreamingError {
  error: string;
  stack_trace: string;
}

export interface InputPrompt {
  id: number;
  prompt: string;
  content: string;
  active: boolean;
  is_public: boolean;
}

export interface EditPromptModalProps {
  onClose: () => void;

  promptId: number;
  editInputPrompt: (
    promptId: number,
    values: CreateInputPromptRequest
  ) => Promise<void>;
}
export interface CreateInputPromptRequest {
  prompt: string;
  content: string;
}

export interface AddPromptModalProps {
  onClose: () => void;
  onSubmit: (promptData: CreateInputPromptRequest) => void;
}
export interface PromptData {
  id: number;
  prompt: string;
  content: string;
}
// We need to update the constructSubQuestions function so it can take in either SubQueryDetail or SubQuestionDetail and given current state of subQuestions, build it up

/**
 * // Start of Selection
 */

export interface BaseQuestionIdentifier {
  level: number;
  level_question_num: number;
}

export interface SubQuestionDetail extends BaseQuestionIdentifier {
  question: string;
  answer: string;
  sub_queries?: SubQueryDetail[] | null;
  context_docs?: { top_documents: OnyxDocument[] } | null;
  is_complete?: boolean;
  is_stopped?: boolean;
  answer_streaming?: boolean;
}

export interface SubQueryDetail {
  query: string;
  query_id: number;
  doc_ids?: number[] | null;
}

export const constructSubQuestions = (
  subQuestions: SubQuestionDetail[],
  newDetail:
    | SubQuestionPiece
    | SubQueryPiece
    | AgentAnswerPiece
    | SubQuestionSearchDoc
    | DocumentsResponse
    | StreamStopInfo
): SubQuestionDetail[] => {
  if (!newDetail) {
    return subQuestions;
  }
  if (newDetail.level_question_num == 0) {
    return subQuestions;
  }

  const updatedSubQuestions = [...subQuestions];

  if ("stop_reason" in newDetail) {
    const { level, level_question_num } = newDetail;
    let subQuestion = updatedSubQuestions.find(
      (sq) => sq.level === level && sq.level_question_num === level_question_num
    );
    if (subQuestion) {
      if (newDetail.stream_type == "sub_answer") {
        subQuestion.answer_streaming = false;
      } else {
        subQuestion.is_complete = true;
        subQuestion.is_stopped = true;
      }
    }
  } else if ("top_documents" in newDetail) {
    const { level, level_question_num, top_documents } = newDetail;
    let subQuestion = updatedSubQuestions.find(
      (sq) => sq.level === level && sq.level_question_num === level_question_num
    );
    if (!subQuestion) {
      subQuestion = {
        level: level ?? 0,
        level_question_num: level_question_num ?? 0,
        question: "",
        answer: "",
        sub_queries: [],
        context_docs: { top_documents },
        is_complete: false,
      };
    } else {
      subQuestion.context_docs = { top_documents };
    }
  } else if ("answer_piece" in newDetail) {
    // Handle AgentAnswerPiece
    const { level, level_question_num, answer_piece } = newDetail;
    // Find or create the relevant SubQuestionDetail
    let subQuestion = updatedSubQuestions.find(
      (sq) => sq.level === level && sq.level_question_num === level_question_num
    );

    if (!subQuestion) {
      subQuestion = {
        level,
        level_question_num,
        question: "",
        answer: "",
        sub_queries: [],
        context_docs: undefined,
        is_complete: false,
      };
      updatedSubQuestions.push(subQuestion);
    }

    // Append to the answer
    subQuestion.answer += answer_piece;
  } else if ("sub_question" in newDetail) {
    // Handle SubQuestionPiece
    const { level, level_question_num, sub_question } = newDetail;

    // Find or create the relevant SubQuestionDetail
    let subQuestion = updatedSubQuestions.find(
      (sq) => sq.level === level && sq.level_question_num === level_question_num
    );

    if (!subQuestion) {
      subQuestion = {
        level,
        level_question_num,
        question: "",
        answer: "",
        sub_queries: [],
        context_docs: undefined,
        is_complete: false,
      };
      updatedSubQuestions.push(subQuestion);
    }

    // Append to the question
    subQuestion.question += sub_question;
  } else if ("sub_query" in newDetail) {
    // Handle SubQueryPiece
    const { level, level_question_num, query_id, sub_query } = newDetail;

    // Find the relevant SubQuestionDetail
    let subQuestion = updatedSubQuestions.find(
      (sq) => sq.level === level && sq.level_question_num === level_question_num
    );

    if (!subQuestion) {
      // If we receive a sub_query before its parent question, create a placeholder
      subQuestion = {
        level,
        level_question_num: level_question_num,
        question: "",
        answer: "",
        sub_queries: [],
        context_docs: undefined,
      };
      updatedSubQuestions.push(subQuestion);
    }

    // Find or create the relevant SubQueryDetail
    let subQuery = subQuestion.sub_queries?.find(
      (sq) => sq.query_id === query_id
    );

    if (!subQuery) {
      subQuery = { query: "", query_id };
      subQuestion.sub_queries = [...(subQuestion.sub_queries || []), subQuery];
    }

    // Append to the query
    subQuery.query += sub_query;
  }

  return updatedSubQuestions;
};
