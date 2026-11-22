"use client";

import { useEffect, useRef } from "react";
import { useTranslations } from "next-intl";
import { Button, MessageCard } from "@opal/components";
import { SvgClock } from "@opal/icons";
import { useNavigation } from "@opal/navigation";
import { isRunUnviewed } from "@/app/craft/v1/tasks/utils";
import { CHAT_COLUMN_ROW, CHAT_GUTTER } from "@/lib/chat/layout";
import {
  revalidateChatScheduledRunViews,
  useScheduledRunOfChat,
  useScheduledTaskFormat,
} from "@/lib/scheduledTasks/hooks";
import { scheduledTaskHref } from "@/lib/scheduledTasks/paths";
import { markScheduledRunViewed } from "@/lib/scheduledTasks/svc";
import { cn } from "@opal/utils";

interface ScheduledRunBannerProps {
  chatSessionId: string;
}

/** Names the task that created this chat. Renders nothing for other chats.
 * Opening the chat marks the run viewed. */
export default function ScheduledRunBanner({
  chatSessionId,
}: ScheduledRunBannerProps) {
  const t = useTranslations("scheduledTasks.banner");
  const navigation = useNavigation();
  const timeFormat = useScheduledTaskFormat();
  const { data: run, mutate } = useScheduledRunOfChat(chatSessionId);
  const markedRevision = useRef<string | null>(null);

  useEffect(() => {
    if (!run || run.status === "RUNNING" || !isRunUnviewed(run)) return;
    const key = `${run.run_id}:${run.revision}`;
    if (markedRevision.current === key) return;
    markedRevision.current = key;
    void markScheduledRunViewed(run.task_id, run.run_id, run.revision)
      .then(() =>
        Promise.all([mutate(), revalidateChatScheduledRunViews(run.task_id)])
      )
      .catch(() => {
        markedRevision.current = null;
      });
  }, [run, mutate]);

  if (!run) return null;
  return (
    <div
      className={cn(CHAT_COLUMN_ROW, CHAT_GUTTER, "pt-2")}
      data-testid="scheduled-run-banner"
    >
      <MessageCard
        variant={run.status === "AWAITING_APPROVAL" ? "warning" : "default"}
        icon={SvgClock}
        title={t("title", { task: run.task_name })}
        description={
          run.status === "RUNNING" || run.status === "AWAITING_APPROVAL"
            ? t("inFlight", { status: run.status })
            : t("startedAt", { time: timeFormat.absolute(run.started_at) })
        }
        rightChildren={
          <Button
            prominence="tertiary"
            size="sm"
            {...navigation.linkTo(scheduledTaskHref(run.task_id))}
          >
            {t("viewTask")}
          </Button>
        }
      />
    </div>
  );
}
