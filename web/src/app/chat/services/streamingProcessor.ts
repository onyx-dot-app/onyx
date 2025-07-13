import {
  Message,
  RetrievalType,
  FileDescriptor,
  SubQuestionDetail,
  ToolCallMetadata,
  BackendMessage,
  constructSubQuestions,
  DocumentsResponse,
  AgenticMessageResponseIDInfo,
  UserKnowledgeFilePacket,
  FileChatDisplay,
  StreamingError,
  ChatFileType,
  MessageResponseIDInfo,
} from "../interfaces";
import {
  OnyxDocument,
  StreamStopReason,
  StreamStopInfo,
  SubQueryPiece,
  SubQuestionPiece,
  AgentAnswerPiece,
  AnswerPiecePacket,
  DocumentInfoPacket,
  RefinedAnswerImprovement,
} from "@/lib/search/interfaces";
import { getLastSuccessfulMessageId, PacketType } from "../lib";

export interface StreamingProcessorDependencies {
  updateChatState: (state: string, sessionId?: string) => void;
  getCurrentChatState: () => string;
  setAgenticGenerating: (generating: boolean) => void;
  updateCanContinue: (canContinue: boolean, sessionId: string) => void;
  upsertToCompleteMessageMap: (params: {
    messages: Message[];
    replacementsMap?: Map<number, number> | null;
    completeMessageMapOverride?: Map<number, Message> | null;
    chatSessionId?: string;
  }) => { sessionId: string; messageMap: Map<number, Message> };
  setSelectedMessageForDocDisplay: (messageId: number | null) => void;
  setUncaughtError: (error: string | null) => void;
  setLoadingError: (error: string | null) => void;
  setAlternativeGeneratingAssistant: (assistant: any) => void;
  setSubmittedMessage: (message: string) => void;
  resetRegenerationState: (sessionId: string) => void;
}

export interface StreamingState {
  answer: string;
  second_level_answer: string;
  query: string | null;
  retrievalType: RetrievalType;
  documents: OnyxDocument[];
  aiMessageImages: FileDescriptor[] | null;
  agenticDocs: OnyxDocument[] | null;
  error: string | null;
  stackTrace: string | null;
  sub_questions: SubQuestionDetail[];
  is_generating: boolean;
  second_level_generating: boolean;
  finalMessage: BackendMessage | null;
  toolCall: ToolCallMetadata | null;
  isImprovement: boolean | undefined;
  isStreamingQuestions: boolean;
  includeAgentic: boolean;
  secondLevelMessageId: number | null;
  isAgentic: boolean;
  files: FileDescriptor[];
}

export interface InitialFetchDetails {
  user_message_id: number;
  assistant_message_id: number;
  frozenMessageMap: Map<number, Message>;
}

export class StreamingProcessor {
  constructor(private deps: StreamingProcessorDependencies) {}

  initializeStreamingState(): StreamingState {
    return {
      answer: "",
      second_level_answer: "",
      query: null,
      retrievalType: RetrievalType.None,
      documents: [],
      aiMessageImages: null,
      agenticDocs: null,
      error: null,
      stackTrace: null,
      sub_questions: [],
      is_generating: false,
      second_level_generating: false,
      finalMessage: null,
      toolCall: null,
      isImprovement: undefined,
      isStreamingQuestions: true,
      includeAgentic: false,
      secondLevelMessageId: null,
      isAgentic: false,
      files: [],
    };
  }

  processInitialPacket(
    packet: PacketType,
    regenerationRequest: any,
    currMessage: string,
    parentMessage: Message | null,
    currentMap: Map<number, Message>,
    currChatSessionId: string,
    files: FileDescriptor[]
  ): InitialFetchDetails | null {
    if (!Object.hasOwn(packet, "user_message_id")) {
      console.error("First packet should contain message response info");
      if (Object.hasOwn(packet, "error")) {
        const error = (packet as StreamingError).error;
        this.deps.setLoadingError(error);
        this.deps.updateChatState("input");
        return null;
      }
      return null;
    }

    const messageResponseIDInfo = packet as MessageResponseIDInfo;
    const user_message_id = messageResponseIDInfo.user_message_id!;
    const assistant_message_id =
      messageResponseIDInfo.reserved_assistant_message_id;

    // Create initial message updates
    const messageUpdates: Message[] = [
      {
        messageId: regenerationRequest
          ? regenerationRequest?.parentMessage?.messageId!
          : user_message_id,
        message: currMessage,
        type: "user",
        files: files,
        toolCall: null,
        parentMessageId: parentMessage?.messageId || -3, // SYSTEM_MESSAGE_ID
      },
    ];

    if (parentMessage && !regenerationRequest) {
      messageUpdates.push({
        ...parentMessage,
        childrenMessageIds: (parentMessage.childrenMessageIds || []).concat([
          user_message_id,
        ]),
        latestChildMessageId: user_message_id,
      });
    }

    const { messageMap: currentFrozenMessageMap } =
      this.deps.upsertToCompleteMessageMap({
        messages: messageUpdates,
        chatSessionId: currChatSessionId,
        completeMessageMapOverride: currentMap,
      });

    // Reset regeneration state (matching original logic)
    this.deps.resetRegenerationState(currChatSessionId);

    return {
      frozenMessageMap: currentFrozenMessageMap,
      assistant_message_id,
      user_message_id,
    };
  }

  processPacket(
    packet: PacketType,
    streamingState: StreamingState,
    frozenSessionId: string,
    user_message_id: number
  ): StreamingState {
    const newState = { ...streamingState };

    // Handle agentic message IDs
    if (Object.hasOwn(packet, "agentic_message_ids")) {
      const agenticMessageIds = (packet as AgenticMessageResponseIDInfo)
        .agentic_message_ids;
      const level1MessageId = agenticMessageIds.find((item) => item.level === 1)
        ?.message_id;
      if (level1MessageId) {
        newState.secondLevelMessageId = level1MessageId;
        newState.includeAgentic = true;
      }
    }

    // Update chat state to streaming if currently loading
    if (this.deps.getCurrentChatState() === "loading") {
      this.deps.updateChatState("streaming", frozenSessionId);
    }

    // Handle level information
    if (Object.hasOwn(packet, "level")) {
      if ((packet as any).level === 1) {
        newState.second_level_generating = true;
      }
    }

    // Handle user files
    if (Object.hasOwn(packet, "user_files")) {
      const userFiles = (packet as UserKnowledgeFilePacket).user_files;
      const newUserFiles = userFiles.filter(
        (newFile) =>
          !newState.files.some((existingFile) => existingFile.id === newFile.id)
      );
      newState.files = newState.files.concat(newUserFiles);
    }

    // Handle agentic flag
    if (Object.hasOwn(packet, "is_agentic")) {
      newState.isAgentic = (packet as any).is_agentic;
    }

    // Handle refined answer improvement
    if (Object.hasOwn(packet, "refined_answer_improvement")) {
      newState.isImprovement = (
        packet as RefinedAnswerImprovement
      ).refined_answer_improvement;
    }

    // Handle stream type
    if (Object.hasOwn(packet, "stream_type")) {
      if ((packet as any).stream_type == "main_answer") {
        newState.is_generating = false;
        newState.second_level_generating = true;
      }
    }

    // Handle sub-questions and streaming
    // Continuously refine the sub_questions based on the packets that we receive
    if (
      Object.hasOwn(packet, "stop_reason") &&
      Object.hasOwn(packet, "level_question_num")
    ) {
      if ((packet as StreamStopInfo).stream_type == "main_answer") {
        this.deps.updateChatState("streaming", frozenSessionId);
      }
      if (
        (packet as StreamStopInfo).stream_type == "sub_questions" &&
        (packet as StreamStopInfo).level_question_num == undefined
      ) {
        newState.isStreamingQuestions = false;
      }
      newState.sub_questions = constructSubQuestions(
        newState.sub_questions,
        packet as StreamStopInfo
      );
    } else if (Object.hasOwn(packet, "sub_question")) {
      this.deps.updateChatState("toolBuilding", frozenSessionId);
      newState.isAgentic = true;
      newState.is_generating = true;
      newState.sub_questions = constructSubQuestions(
        newState.sub_questions,
        packet as SubQuestionPiece
      );
      this.deps.setAgenticGenerating(true);
    } else if (Object.hasOwn(packet, "sub_query")) {
      newState.sub_questions = constructSubQuestions(
        newState.sub_questions,
        packet as SubQueryPiece
      );
    } else if (
      Object.hasOwn(packet, "answer_piece") &&
      Object.hasOwn(packet, "answer_type") &&
      (packet as AgentAnswerPiece).answer_type === "agent_sub_answer"
    ) {
      newState.sub_questions = constructSubQuestions(
        newState.sub_questions,
        packet as AgentAnswerPiece
      );
    } else if (Object.hasOwn(packet, "answer_piece")) {
      // Mark every sub_question's is_generating as false
      newState.sub_questions = newState.sub_questions.map((subQ) => ({
        ...subQ,
        is_generating: false,
      }));

      if (Object.hasOwn(packet, "level") && (packet as any).level === 1) {
        newState.second_level_answer += (
          packet as AnswerPiecePacket
        ).answer_piece;
      } else {
        newState.answer += (packet as AnswerPiecePacket).answer_piece;
      }
    } else if (
      Object.hasOwn(packet, "top_documents") &&
      Object.hasOwn(packet, "level_question_num") &&
      (packet as DocumentsResponse).level_question_num != undefined
    ) {
      const documentsResponse = packet as DocumentsResponse;
      newState.sub_questions = constructSubQuestions(
        newState.sub_questions,
        documentsResponse
      );

      if (
        documentsResponse.level_question_num === 0 &&
        documentsResponse.level == 0
      ) {
        newState.documents = (packet as DocumentsResponse).top_documents;
      } else if (
        documentsResponse.level_question_num === 0 &&
        documentsResponse.level == 1
      ) {
        newState.agenticDocs = (packet as DocumentsResponse).top_documents;
      }
    } else if (Object.hasOwn(packet, "top_documents")) {
      newState.documents = (packet as DocumentInfoPacket).top_documents;
      newState.retrievalType = RetrievalType.Search;

      if (newState.documents && newState.documents.length > 0) {
        this.deps.setSelectedMessageForDocDisplay(user_message_id);
      }
    } else if (Object.hasOwn(packet, "tool_name")) {
      // Handle tool calls
      newState.toolCall = {
        tool_name: (packet as ToolCallMetadata).tool_name,
        tool_args: (packet as ToolCallMetadata).tool_args,
        tool_result: (packet as ToolCallMetadata).tool_result,
      };

      if (!newState.toolCall.tool_name.includes("agent")) {
        if (
          !newState.toolCall.tool_result ||
          newState.toolCall.tool_result == undefined
        ) {
          this.deps.updateChatState("toolBuilding", frozenSessionId);
        } else {
          this.deps.updateChatState("streaming", frozenSessionId);
        }

        // Set query for search tool
        if (newState.toolCall.tool_name == "search") {
          newState.query = newState.toolCall.tool_args["query"];
        }
      } else {
        newState.toolCall = null;
      }
    } else if (Object.hasOwn(packet, "file_ids")) {
      newState.aiMessageImages = (packet as FileChatDisplay).file_ids.map(
        (fileId) => ({
          id: fileId,
          type: ChatFileType.IMAGE,
        })
      );
    } else if (
      Object.hasOwn(packet, "error") &&
      (packet as any).error != null
    ) {
      // Handle errors
      if (
        newState.sub_questions.length > 0 &&
        newState.sub_questions
          .filter((q) => q.level === 0)
          .every((q) => q.is_stopped === true)
      ) {
        this.deps.setUncaughtError((packet as StreamingError).error);
        this.deps.updateChatState("input");
        this.deps.setAgenticGenerating(false);
        this.deps.setAlternativeGeneratingAssistant(null);
        this.deps.setSubmittedMessage("");

        throw new Error((packet as StreamingError).error);
      } else {
        newState.error = (packet as StreamingError).error;
        newState.stackTrace = (packet as StreamingError).stack_trace;
      }
    } else if (Object.hasOwn(packet, "message_id")) {
      newState.finalMessage = packet as BackendMessage;
    } else if (Object.hasOwn(packet, "stop_reason")) {
      const stop_reason = (packet as StreamStopInfo).stop_reason;
      if (stop_reason === StreamStopReason.CONTEXT_LENGTH) {
        this.deps.updateCanContinue(true, frozenSessionId);
      }
    }

    return newState;
  }
}
