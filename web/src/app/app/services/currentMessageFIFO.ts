import { PacketType, sendMessage, SendMessageParams } from "./lib";

export class CurrentMessageFIFO {
  private stack: PacketType[] = [];
  isComplete: boolean = false;
  error: string | null = null;

  push(packetBunch: PacketType) {
    this.stack.push(packetBunch);
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
  } catch (error: unknown) {
    if (error instanceof Error) {
      if (error.name === "AbortError") {
        console.debug("Stream aborted");
      } else {
        stack.error = error.message;
      }
    } else {
      stack.error = String(error);
    }
  } finally {
    stack.isComplete = true;
  }
}
