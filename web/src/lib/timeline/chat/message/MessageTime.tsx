"use client";

import { isToday, isYesterday } from "date-fns";
import { useFormatter, useTranslations } from "next-intl";
import { Text } from "@opal/components";

/** Hides a message's footer row until the message (a `group/message`) is
 * hovered for 250ms. Open menus, keyboard focus anywhere in the message and
 * touch screens keep it shown. */
export const MESSAGE_FOOTER_REVEAL =
  "opacity-0 transition-opacity duration-0 group-hover/message:opacity-100 group-hover/message:delay-250 group-hover/message:duration-150 group-has-[:focus-visible]/message:opacity-100 has-[[aria-expanded=true]]:opacity-100 no-hover:opacity-100";

interface MessageTimeProps {
  timeSent: string;
}

export default function MessageTime({ timeSent }: MessageTimeProps) {
  const t = useTranslations("chat.messages.messageTime");
  const format = useFormatter();
  const date = new Date(timeSent);
  if (Number.isNaN(date.getTime())) return null;

  const time = format.dateTime(date, { timeStyle: "short" });
  const label = isToday(date)
    ? time
    : isYesterday(date)
      ? t("yesterdayLabel", { time })
      : format.dateTime(date, { dateStyle: "medium", timeStyle: "short" });

  return (
    <Text
      as="p"
      font="secondary-body"
      color="text-03"
      wordWrap="whitespace-nowrap"
      tooltip={format.dateTime(date, { dateStyle: "full", timeStyle: "short" })}
      data-testid="message-time"
    >
      {label}
    </Text>
  );
}
