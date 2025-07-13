import { Message } from "../interfaces";
import { getLastSuccessfulMessageId } from "../lib";

export interface MessageUpdaterDependencies {
  upsertToCompleteMessageMap: (params: {
    messages: Message[];
    replacementsMap?: Map<number, number> | null;
    completeMessageMapOverride?: Map<number, Message> | null;
    chatSessionId?: string;
  }) => { sessionId: string; messageMap: Map<number, Message> };
}

export interface MessageUpdateParams {
  regenerationRequest: any;
  initialFetchDetails: {
    user_message_id: number;
    assistant_message_id: number;
    frozenMessageMap: Map<number, Message>;
  };
  streamingState: {
    answer: string;
    second_level_answer: string;
    query: string | null;
    retrievalType: any;
    documents: any[];
    aiMessageImages: any[] | null;
    agenticDocs: any[] | null;
    error: string | null;
    stackTrace: string | null;
    sub_questions: any[];
    is_generating: boolean;
    second_level_generating: boolean;
    finalMessage: any;
    toolCall: any;
    isImprovement: boolean | undefined;
    isStreamingQuestions: boolean;
    includeAgentic: boolean;
    secondLevelMessageId: number | null;
    isAgentic: boolean;
    files: any[];
  };
  currMessage: string;
  parentMessage: Message | null;
  currentMap: Map<number, Message>;
  frozenSessionId: string;
  alternativeAssistant: any;
  mapKeys: number[];
}

export class MessageUpdater {
  constructor(private deps: MessageUpdaterDependencies) {}

  updateMessages(params: MessageUpdateParams): Map<number, Message> {
    const {
      regenerationRequest,
      initialFetchDetails,
      streamingState,
      currMessage,
      parentMessage,
      currentMap,
      frozenSessionId,
      alternativeAssistant,
      mapKeys,
    } = params;

    const { upsertToCompleteMessageMap } = this.deps;

    const updateFn = (messages: Message[]) => {
      const replacementsMap = regenerationRequest
        ? new Map([
            [
              regenerationRequest?.parentMessage?.messageId,
              regenerationRequest?.parentMessage?.messageId,
            ],
            [
              regenerationRequest?.messageId,
              initialFetchDetails?.assistant_message_id,
            ],
          ] as [number, number][])
        : null;

      const newMessageDetails = upsertToCompleteMessageMap({
        messages: messages,
        replacementsMap: replacementsMap,
        completeMessageMapOverride: currentMap,
        chatSessionId: frozenSessionId,
      });
      return newMessageDetails.messageMap;
    };

    const systemMessageId = Math.min(...mapKeys);
    const lastSuccessfulMessageId = getLastSuccessfulMessageId([]); // This should be passed in

    // Parent message fallback logic (matching original implementation)
    const finalParentMessage =
      parentMessage || initialFetchDetails.frozenMessageMap?.get(-3)!; // SYSTEM_MESSAGE_ID

    const messages: Message[] = [
      {
        messageId: regenerationRequest
          ? regenerationRequest?.parentMessage?.messageId!
          : initialFetchDetails.user_message_id!,
        message: currMessage,
        type: "user",
        files: streamingState.files,
        toolCall: null,
        parentMessageId:
          (finalParentMessage?.messageId || lastSuccessfulMessageId) ??
          systemMessageId,
        childrenMessageIds: [
          ...(regenerationRequest?.parentMessage?.childrenMessageIds || []),
          initialFetchDetails.assistant_message_id!,
        ],
        latestChildMessageId: initialFetchDetails.assistant_message_id,
      },
      {
        isStreamingQuestions: streamingState.isStreamingQuestions,
        is_generating: streamingState.is_generating,
        isImprovement: streamingState.isImprovement,
        messageId: initialFetchDetails.assistant_message_id!,
        message: streamingState.error || streamingState.answer,
        second_level_message: streamingState.second_level_answer,
        type: streamingState.error ? "error" : "assistant",
        retrievalType: streamingState.retrievalType,
        query:
          streamingState.finalMessage?.rephrased_query || streamingState.query,
        documents: streamingState.documents,
        citations: streamingState.finalMessage?.citations || {},
        files:
          streamingState.finalMessage?.files ||
          streamingState.aiMessageImages ||
          [],
        toolCall:
          streamingState.finalMessage?.tool_call || streamingState.toolCall,
        parentMessageId: regenerationRequest
          ? regenerationRequest?.parentMessage?.messageId!
          : initialFetchDetails.user_message_id,
        alternateAssistantID: alternativeAssistant?.id,
        stackTrace: streamingState.stackTrace,
        overridden_model: streamingState.finalMessage?.overridden_model,
        stopReason: null, // This should be passed in
        sub_questions: streamingState.sub_questions,
        second_level_generating: streamingState.second_level_generating,
        agentic_docs: streamingState.agenticDocs,
        is_agentic: streamingState.isAgentic,
      },
    ];

    // Add agentic message if needed
    if (streamingState.includeAgentic && streamingState.secondLevelMessageId) {
      messages.push({
        messageId: streamingState.secondLevelMessageId!,
        message: streamingState.second_level_answer,
        type: "assistant" as const,
        files: [],
        toolCall: null,
        parentMessageId: initialFetchDetails.assistant_message_id!,
      });
    }

    return updateFn(messages);
  }
}
