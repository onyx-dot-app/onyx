"use client";

import useSWR from "swr";
import { useTranslations } from "next-intl";
import { Button, Dropdown, InputSwitch, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import {
  SvgClock,
  SvgEdit,
  SvgMoreHorizontal,
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
                key="edit"
                icon={SvgEdit}
                prominence="secondary"
                {...navigation.linkTo(editScheduledTaskHref(task.id))}
              >
                {tActions("edit")}
              </Button>,
              <Dropdown key="menu" align="end">
                <Dropdown.Trigger asChild>
                  <Button
                    prominence="tertiary"
                    icon={SvgMoreHorizontal}
                    aria-label={t("menu")}
                    tooltip={t("menu")}
                  />
                </Dropdown.Trigger>
                <Dropdown.Data
                  label={t("menu")}
                  items={[
                    {
                      kind: "action",
                      id: "delete",
                      icon: SvgTrash,
                      title: tActions("delete"),
                      danger: true,
                      disabled: actions.busy,
                      onSelect: actions.requestDelete,
                    },
                  ]}
                />
              </Dropdown>,
              <Section
                key="switch"
                flexDirection="row"
                width="auto"
                height="auto"
                gap={1}
                padding={1}
              >
                <Text font="main-ui-body" color="text-03">
                  {t("switch.title")}
                </Text>
                <InputSwitch
                  aria-label={t("switch.label", { name: task.name })}
                  checked={task.status === "ACTIVE"}
                  disabled={actions.busy}
                  onCheckedChange={actions.toggleStatus}
                />
              </Section>,
            ]
          : undefined
      }
    >
      {actions.modal}
    </CustomizeDetailLayout>
  );
}
