import { Message } from "../interfaces";
import { buildLatestMessageChain, getLastSuccessfulMessageId } from "../lib";
import { Persona } from "../../admin/assistants/interfaces";
import { PopupSpec } from "@/components/admin/connectors/Popup";

export interface MessagePreprocessorDependencies {
  currentMessageMap: (
    messageDetail: Map<string | null, Map<number, Message>>
  ) => Map<number, Message>;
  completeMessageDetail: Map<string | null, Map<number, Message>>;
  updateCompleteMessageDetail: (
    sessionId: string | null,
    messageMap: Map<number, Message>
  ) => void;
  messageHistory: Message[];
  setPopup: (popup: PopupSpec | null) => void;
  getCurrentChatState: () => string;
  setAlternativeGeneratingAssistant: (assistant: Persona | null) => void;
  clientScrollToBottom: () => void;
  resetInputBar: () => void;
}

export interface PreprocessingResult {
  currentMap: Map<number, Message>;
  currentHistory: Message[];
  parentMessage: Message | null;
  currentAssistantId: number;
  currMessage: string;
  messageToResend: Message | undefined;
  messageToResendIndex: number | null;
}

export interface RegenerationRequest {
  messageId: number;
  parentMessage: Message;
  forceSearch?: boolean;
}

export class MessagePreprocessor {
  constructor(private deps: MessagePreprocessorDependencies) {}

  preprocessMessage(params: {
    messageIdToResend?: number;
    messageOverride?: string;
    alternativeAssistantOverride?: Persona | null;
    regenerationRequest?: RegenerationRequest | null;
    message: string;
    alternativeAssistant: Persona | null;
    liveAssistant: Persona | undefined;
    frozenSessionId: string;
  }): PreprocessingResult {
    const {
      messageIdToResend,
      messageOverride,
      alternativeAssistantOverride,
      regenerationRequest,
      message,
      alternativeAssistant,
      liveAssistant,
      frozenSessionId,
    } = params;

    const {
      currentMessageMap,
      completeMessageDetail,
      updateCompleteMessageDetail,
      messageHistory,
      setPopup,
      getCurrentChatState,
      setAlternativeGeneratingAssistant,
      clientScrollToBottom,
      resetInputBar,
    } = this.deps;

    // Validate chat state
    if (getCurrentChatState() != "input") {
      if (getCurrentChatState() == "uploading") {
        setPopup({
          message: "Please wait for the content to upload",
          type: "error",
        });
      } else {
        setPopup({
          message: "Please wait for the response to complete",
          type: "error",
        });
      }
      throw new Error("Invalid chat state");
    }

    setAlternativeGeneratingAssistant(alternativeAssistantOverride || null);
    clientScrollToBottom();

    // Get current message state
    let currentMap = currentMessageMap(completeMessageDetail);
    let currentHistory = buildLatestMessageChain(currentMap);
    let lastMessage = currentHistory[currentHistory.length - 1];

    // Clean up error messages if needed
    if (
      lastMessage &&
      lastMessage.type === "error" &&
      !messageIdToResend &&
      !regenerationRequest
    ) {
      currentMap = this.cleanupErrorMessage(
        currentMap,
        lastMessage,
        frozenSessionId
      );
      currentHistory = buildLatestMessageChain(currentMap);
      lastMessage = currentHistory[currentHistory.length - 1];
    }

    // Handle message resend logic
    const messageToResend = messageHistory.find(
      (message) => message.messageId === messageIdToResend
    );

    if (!messageToResend && messageIdToResend !== undefined) {
      setPopup({
        message:
          "Failed to re-send message - please refresh the page and try again.",
        type: "error",
      });
      throw new Error("Message to resend not found");
    }

    const messageToResendIndex = messageToResend
      ? messageHistory.indexOf(messageToResend)
      : null;

    // Determine current message content
    let currMessage = messageToResend ? messageToResend.message : message;
    if (messageOverride) {
      currMessage = messageOverride;
    }

    // Determine assistant ID
    let currentAssistantId: number;
    if (alternativeAssistantOverride) {
      currentAssistantId = alternativeAssistantOverride.id;
    } else if (alternativeAssistant) {
      currentAssistantId = alternativeAssistant.id;
    } else {
      if (liveAssistant) {
        currentAssistantId = liveAssistant.id;
      } else {
        currentAssistantId = 0; // Fallback if no assistant is live
      }
    }

    // Determine parent message
    const currMessageHistory =
      messageToResendIndex !== null
        ? currentHistory.slice(0, messageToResendIndex)
        : currentHistory;

    const messageToResendParent: Message | null =
      messageToResend?.parentMessageId !== null &&
      messageToResend?.parentMessageId !== undefined
        ? currentMap.get(messageToResend.parentMessageId) || null
        : null;

    let parentMessage: Message | null =
      messageToResendParent ||
      (currMessageHistory.length > 0
        ? currMessageHistory[currMessageHistory.length - 1]
        : null) ||
      (currentMap.size === 1
        ? Array.from(currentMap.values())[0] || null
        : null);

    resetInputBar();

    return {
      currentMap,
      currentHistory,
      parentMessage,
      currentAssistantId,
      currMessage,
      messageToResend,
      messageToResendIndex,
    };
  }

  private cleanupErrorMessage(
    currentMap: Map<number, Message>,
    lastMessage: Message,
    frozenSessionId: string
  ): Map<number, Message> {
    const { updateCompleteMessageDetail } = this.deps;

    const newMap = new Map(currentMap);
    const parentId = lastMessage.parentMessageId;

    // Remove the error message itself
    newMap.delete(lastMessage.messageId);

    // Remove the parent message + update the parent of the parent to no longer
    // link to the parent
    if (parentId !== null && parentId !== undefined) {
      const parentOfError = newMap.get(parentId);
      if (parentOfError) {
        const grandparentId = parentOfError.parentMessageId;
        if (grandparentId !== null && grandparentId !== undefined) {
          const grandparent = newMap.get(grandparentId);
          if (grandparent) {
            // Update grandparent to no longer link to parent
            const updatedGrandparent = {
              ...grandparent,
              childrenMessageIds: (grandparent.childrenMessageIds || []).filter(
                (id) => id !== parentId
              ),
              latestChildMessageId:
                grandparent.latestChildMessageId === parentId
                  ? null
                  : grandparent.latestChildMessageId,
            };
            newMap.set(grandparentId, updatedGrandparent);
          }
        }
        // Remove the parent message
        newMap.delete(parentId);
      }
    }

    // Update the state immediately so subsequent logic uses the cleaned map
    updateCompleteMessageDetail(frozenSessionId, newMap);
    console.log("Removed previous error message ID:", lastMessage.messageId);

    return newMap;
  }
}
