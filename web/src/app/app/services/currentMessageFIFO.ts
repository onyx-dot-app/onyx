import {
  ChatSendRejectedError,
  PacketType,
  sendMessage,
  SendMessageParams,
} from "@/app/app/services/lib";

export class CurrentMessageFIFO {
  private stack: PacketType[] = [];
  isComplete: boolean = false;
  error: string | null = null;
  private readonly admission = Promise.withResolvers<number | null>();
  /** Accepted stream ID, or null if the server finishes without admission. */
  readonly acknowledged = this.admission.promise;

  constructor() {
    // Completion handlers consume errors after queued packets drain.
    void this.acknowledged.catch(() => {});
  }

  push(packetBunch: PacketType) {
    this.stack.push(packetBunch);
    if ("reserved_assistant_message_id" in packetBunch) {
      this.admission.resolve(packetBunch.reserved_assistant_message_id);
    } else if ("responses" in packetBunch) {
      this.admission.resolve(packetBunch.user_message_id);
    }
  }

  complete(error?: unknown) {
    this.isComplete = true;
    if (error !== undefined) this.admission.reject(error);
    else this.admission.resolve(null);
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
