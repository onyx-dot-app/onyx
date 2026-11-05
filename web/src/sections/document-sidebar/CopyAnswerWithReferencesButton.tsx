"use client";

import { useTranslations } from "next-intl";
import { CopyButton } from "@opal/components";
import { Message, ResearchType } from "@/app/app/interfaces";
import {
  getCitations,
  getTextContent,
  isStreamingComplete,
} from "@/app/app/services/packetUtils";
import { PacketType, StopReason } from "@/app/app/services/streamingModels";
import { removeThinkingTokens } from "@/app/app/services/thinkingTokens";
import { buildAnswerWithReferences } from "@/lib/chat/answerReferences";

interface CopyAnswerWithReferencesButtonProps {
  message: Message;
}

export default function CopyAnswerWithReferencesButton({
  message,
}: CopyAnswerWithReferencesButtonProps) {
  const t = useTranslations("chat.documentSidebar");
  const answer = removeThinkingTokens(getTextContent(message.packets));
  const citations = getCitations(message.packets);
  const interrupted = message.packets.some(
    (packet) =>
      packet.obj.type === PacketType.ERROR ||
      (packet.obj.type === PacketType.STOP &&
        packet.obj.stop_reason === StopReason.USER_CANCELLED)
  );

  if (
    message.type !== "assistant" ||
    message.researchType === ResearchType.Deep ||
    message.is_generating ||
    !isStreamingComplete(message.packets) ||
    interrupted ||
    typeof answer !== "string" ||
    !answer ||
    citations.length === 0
  ) {
    return null;
  }

  return (
    <CopyButton
      getCopyText={() =>
        buildAnswerWithReferences(answer, citations, message.documents ?? [], {
          title: t("citedSources.title"),
          unavailableSource: t("copyWithReferences.unavailableSource"),
        })
      }
      size="sm"
    >
      {t("copyWithReferences.label")}
    </CopyButton>
  );
}
