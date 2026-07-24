"use client";

import { useTranslations } from "next-intl";
import {
  PacketType,
  PostgresToolPacket,
} from "@/app/app/services/streamingModels";
import {
  MessageRenderer,
  RenderType,
} from "@/app/app/message/messageComponents/types";
import { Text } from "@opal/components";
import { SvgServer } from "@opal/icons";

/**
 * PostgresToolRenderer - Renders knowledge-base metadata query steps.
 *
 * Results go straight back to the LLM; listed documents stream separately so
 * citations resolve. This is a simple status entry that flips to done once the
 * section ends.
 */
export const PostgresToolRenderer: MessageRenderer<PostgresToolPacket, {}> = ({
  packets,
  renderType,
  children,
}) => {
  const t = useTranslations("chat.messages.timeline");
  const isComplete = packets.some(
    (packet) =>
      packet.obj.type === PacketType.SECTION_END ||
      packet.obj.type === PacketType.ERROR
  );
  const statusLabel = isComplete
    ? t("postgres.queried.status")
    : t("postgres.querying.status");

  if (renderType === RenderType.HIGHLIGHT) {
    return children([
      {
        icon: null,
        status: null,
        supportsCollapsible: false,
        timelineLayout: "content",
        content: (
          <Text as="p" font="main-ui-body" color="text-02">
            {statusLabel}
          </Text>
        ),
      },
    ]);
  }

  return children([
    {
      icon: SvgServer,
      status: statusLabel,
      supportsCollapsible: false,
      timelineLayout: "timeline",
      noPaddingRight: true,
      content: <div />,
    },
  ]);
};
