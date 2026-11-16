import { type ReactNode, useEffect, useMemo } from "react";
import { Section } from "@opal/layouts";
import { ShadowDiv, Text } from "@opal/components";
import { Packet, PacketType } from "@/app/app/services/streamingModels";
import { RenderType } from "@/app/app/message/messageComponents/types";

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

interface SandboxCallContentProps {
  renderType: RenderType;
  children: ReactNode;
}

/** The body of a sandbox call step; the collapsed view shows its top. */
export function SandboxCallContent({
  renderType,
  children,
}: SandboxCallContentProps) {
  const content = (
    <Section gap={2} alignItems="stretch" height="fit">
      {children}
    </Section>
  );
  return renderType === RenderType.FULL ? (
    content
  ) : (
    <ShadowDiv
      shadowDirection="bottom-only"
      variant="mask"
      shadowHeight={8}
      className="max-h-24 overflow-hidden"
    >
      {content}
    </ShadowDiv>
  );
}

interface SandboxCallErrorProps {
  error: string;
}

export function SandboxCallError({ error }: SandboxCallErrorProps) {
  return (
    <div className="whitespace-pre-wrap wrap-break-word">
      <Text as="p" font="secondary-body" color="status-error-05">
        {error}
      </Text>
    </div>
  );
}
