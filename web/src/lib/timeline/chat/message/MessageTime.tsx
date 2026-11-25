"use client";

import { isToday, isYesterday } from "date-fns";
import { useFormatter, useTranslations } from "next-intl";
import { Text } from "@opal/components";

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
