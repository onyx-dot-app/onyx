import { useEffect, useMemo } from "react";
import { Packet, PacketType } from "@/app/app/services/streamingModels";

export interface SandboxCallStatus {
  isComplete: boolean;
  error: string | null;
  /** The call ended without a result: Stop, or its code mode cell ended. */
  stopped: boolean;
}

/**
 * How one sandbox call ended, from its end packet (`end`) and the packets that
 * close its step. A stopped call gets no end packet; its step still closes.
 */
export function useSandboxCallStatus(
  packets: Packet[],
  end: { error: string | null } | null,
  stopPacketSeen: boolean,
  onComplete: () => void
): SandboxCallStatus {
  const { ended, errorMessage } = useMemo(() => {
    let ended = false;
    let errorMessage: string | null = null;
    for (const { obj } of packets) {
      if (obj.type === PacketType.ERROR) {
        ended = true;
        errorMessage = obj.message ?? "";
      } else if (obj.type === PacketType.SECTION_END) {
        ended = true;
      }
    }
    return { ended, errorMessage };
  }, [packets]);

  const isComplete = end !== null || ended || stopPacketSeen;
  const error = end?.error ?? errorMessage;

  useEffect(() => {
    if (isComplete) {
      onComplete();
    }
  }, [isComplete, onComplete]);

  return {
    isComplete,
    error,
    stopped: isComplete && end === null && error === null,
  };
}
