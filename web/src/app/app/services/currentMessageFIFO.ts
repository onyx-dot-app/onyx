import {
  ChatSendRejectedError,
  PacketType,
  sendMessage,
  SendMessageParams,
  ApprovalPendingError,
} from "@/app/app/services/lib";
import type { ChatStream } from "@/app/app/types";

export class CurrentMessageFIFO {
  private stack: PacketType[] = [];
  isComplete: boolean = false;
  error: string | null = null;
  /** The server refused the send because the chat waits for a tool approval. */
  approvalPending = false;
  private resolveAdmission: (value: ChatStream | null) => void = () => {};
  private rejectAdmission: (reason: Error) => void = () => {};
  /** Accepted stream, or null if the server finishes without admission. */
  readonly acknowledged: Promise<ChatStream | null>;

  constructor() {
    this.acknowledged = new Promise((resolve, reject) => {
      this.resolveAdmission = resolve;
      this.rejectAdmission = reject;
    });
    // Completion handlers consume errors after queued packets drain.
    void this.acknowledged.catch(() => {});
  }

  push(packetBunch: PacketType) {
    this.stack.push(packetBunch);
    // A sent turn streams under its response, or under the question of a
    // multi-model turn.
    if ("reserved_assistant_message_id" in packetBunch) {
      const responseId = packetBunch.reserved_assistant_message_id;
      this.resolveAdmission({
        stream_id: responseId,
        response_ids: [responseId],
      });
    } else if ("responses" in packetBunch) {
      const questionId = packetBunch.user_message_id;
      this.resolveAdmission(
        questionId === null
          ? null
          : {
              stream_id: questionId,
              response_ids: packetBunch.responses.map(
                (response) => response.message_id
              ),
            }
      );
    }
  }

  complete(error?: unknown) {
    this.isComplete = true;
    if (error !== undefined)
      this.rejectAdmission(
        error instanceof Error ? error : new Error(String(error))
      );
    else this.resolveAdmission(null);
  }

  nextPacket(): PacketType | undefined {
    return this.stack.shift();
  }

  isEmpty(): boolean {
    return this.stack.length === 0;
  }
}

export async function updateCurrentMessageFIFO(
  stack: CurrentMessageFIFO,
  params: SendMessageParams
) {
  try {
    for await (const packet of sendMessage(params)) {
      if (params.signal?.aborted) {
        throw new Error("AbortError");
      }
      stack.push(packet);
    }
    stack.complete();
  } catch (error: unknown) {
    stack.complete(error instanceof ChatSendRejectedError ? undefined : error);
    stack.approvalPending = error instanceof ApprovalPendingError;
    if (error instanceof Error) {
      if (error.name === "AbortError") {
        console.debug("Stream aborted");
      } else {
        stack.error = error.message;
      }
    } else {
      stack.error = String(error);
    }
  }
}
