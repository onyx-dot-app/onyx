"use client";

import useSWR from "swr";
import { useTranslations } from "next-intl";
import { Button } from "@opal/components";
import {
  SvgClock,
  SvgEdit,
  SvgPauseCircle,
  SvgPlayCircle,
  SvgTrash,
  SvgZap,
} from "@opal/icons";
import { useNavigation, useSearchParams } from "@opal/navigation";
import TaskActionPoliciesSummary from "@/app/craft/v1/tasks/components/TaskActionPoliciesSummary";
import { errorHandlingFetcher } from "@/lib/fetcher";
import {
  TASK_REFRESH_INTERVAL_MS,
  useScheduledTaskFormat,
} from "@/lib/scheduledTasks/hooks";
import {
  editScheduledTaskHref,
  SCHEDULED_TASKS_PATH,
  scheduledTaskHref,
  type ScheduledTaskPageTab,
} from "@/lib/scheduledTasks/paths";
import type { ScheduledTaskDetail } from "@/lib/scheduledTasks/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import CustomizeDetailLayout, {
  BackLink,
  DetailOverview,
  type DetailTab,
} from "@/sections/customize/CustomizeDetailLayout";
import ScheduledRunHistory from "@/sections/scheduledTasks/ScheduledRunHistory";
import { useScheduledTaskActions } from "@/sections/scheduledTasks/ScheduledTaskMenu";
import { TaskStatusBadge } from "@/sections/scheduledTasks/StatusBadges";

function parseTab(value: string | null): ScheduledTaskPageTab {
  return value === "overview" ? value : "runs";
}

interface ScheduledTaskPageProps {
  taskId: string;
}

export default function ScheduledTaskPage({ taskId }: ScheduledTaskPageProps) {
  const t = useTranslations("scheduledTasks.detail");
  const tActions = useTranslations("scheduledTasks.actions");
  const navigation = useNavigation();
  const searchParams = useSearchParams();
  const timeFormat = useScheduledTaskFormat();
  const {
    data: task,
    error,
    isLoading,
  } = useSWR<ScheduledTaskDetail>(
    SWR_KEYS.chatScheduledTask(taskId),
    errorHandlingFetcher,
    // Runs end and next runs move in the background.
    { refreshInterval: TASK_REFRESH_INTERVAL_MS }
  );
  const actions = useScheduledTaskActions(task, () =>
    navigation.go(SCHEDULED_TASKS_PATH, { replace: true })
  );
  const schedule = task
    ? timeFormat.schedule(
        task.editor_mode,
        task.cron_expression,
        task.next_run_at
      )
    : undefined;

  const tabs: DetailTab<ScheduledTaskPageTab>[] | null = task
    ? [
        {
          value: "runs",
          label: t("tabs.runs"),
          content: <ScheduledRunHistory taskId={task.id} />,
        },
        {
          value: "overview",
          label: t("tabs.overview"),
          content: (
            <DetailOverview
              descriptionLabel={t("overview.prompt")}
              description={task.prompt}
              facts={[
                { label: t("overview.schedule"), value: schedule ?? "" },
                {
                  label: t("overview.nextRun"),
                  value:
                    task.next_run_at && task.status === "ACTIVE"
                      ? timeFormat.absolute(task.next_run_at)
                      : t("overview.notScheduled"),
                },
                {
                  label: t("overview.lastRun"),
                  value: task.last_run
                    ? timeFormat.absolute(task.last_run.started_at)
                    : t("overview.never"),
                },
              ]}
              footer={
                <TaskActionPoliciesSummary
                  taskId={task.id}
                  url={SWR_KEYS.chatScheduledTaskActionPolicies(task.id)}
                />
              }
            />
          ),
        },
      ]
    : null;

  return (
    <CustomizeDetailLayout
      back={<BackLink to={SCHEDULED_TASKS_PATH} label={t("back")} />}
      icon={SvgClock}
      title={task?.name ?? t("title")}
      description={schedule}
      tags={task && <TaskStatusBadge status={task.status} />}
      loading={isLoading}
      error={error ? t("loadFailed") : false}
      tabs={tabs}
      tab={parseTab(searchParams.get("tab"))}
      onTabChange={(next) =>
        navigation.go(scheduledTaskHref(taskId, next), {
          replace: true,
          scroll: false,
        })
      }
      actions={
        task
          ? [
              <Button
                key="run"
                icon={SvgZap}
                prominence="secondary"
                disabled={actions.busy}
                onClick={actions.runNow}
                data-testid="run-scheduled-task-now"
              >
                {tActions("runNow")}
              </Button>,
              <Button
                key="toggle"
                icon={task.status === "ACTIVE" ? SvgPauseCircle : SvgPlayCircle}
                prominence="secondary"
                disabled={actions.busy}
                onClick={actions.toggleStatus}
              >
                {tActions(task.status === "ACTIVE" ? "pause" : "resume")}
              </Button>,
              <Button
                key="edit"
                icon={SvgEdit}
                prominence="tertiary"
                {...navigation.linkTo(editScheduledTaskHref(task.id))}
              >
                {tActions("edit")}
              </Button>,
              <Button
                key="delete"
                icon={SvgTrash}
                prominence="tertiary"
                disabled={actions.busy}
                onClick={actions.requestDelete}
                aria-label={tActions("delete")}
                tooltip={tActions("delete")}
              />,
            ]
          : undefined
      }
    >
      {actions.modal}
    </CustomizeDetailLayout>
  );
}
