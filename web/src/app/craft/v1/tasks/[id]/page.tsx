"use client";

import { IconLoader } from "@opal/loaders";
import { useCallback, useState } from "react";
import { useTranslations } from "next-intl";
import { useParams, useRouter } from "next/navigation";
import useSWR, { useSWRConfig } from "swr";
import {
  ConfirmationModalLayout,
  Section,
  SettingsLayouts,
  toast,
} from "@opal/layouts";
import { Button, Card, Text } from "@opal/components";
import {
  SvgChevronDown,
  SvgChevronUp,
  SvgClock,
  SvgZap,
  SvgEdit,
  SvgPauseCircle,
  SvgPlayCircle,
  SvgTrash,
} from "@opal/icons";
import {
  deleteScheduledTask,
  runScheduledTaskNow,
  updateScheduledTask,
} from "@/app/craft/v1/tasks/api";
import TaskActionPoliciesSummary from "@/app/craft/v1/tasks/components/TaskActionPoliciesSummary";
import RunHistoryTable from "@/app/craft/v1/tasks/components/RunHistoryTable";

import { taskStatusTag } from "@/app/craft/v1/tasks/components/StatusBadge";
import { TASKS_PATH, taskEditPath } from "@/app/craft/v1/tasks/constants";
import type {
  ScheduledTaskDetail,
  ScheduledTaskListResponse,
  ScheduledTaskStatus,
} from "@/app/craft/v1/tasks/types";
import { humanReadableScheduleFromCron } from "@/app/craft/v1/tasks/schedule";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";

export default function ScheduledTaskDetailPage() {
  const t = useTranslations("craft.tasks.detailPage");
  const tTasks = useTranslations("craft.tasks");
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const taskId = params?.id;

  const { data, error, isLoading, mutate } = useSWR<ScheduledTaskDetail>(
    taskId ? SWR_KEYS.scheduledTask(taskId) : null,
    errorHandlingFetcher,
    { revalidateOnFocus: false }
  );

  const { mutate: globalMutate } = useSWRConfig();

  const [promptExpanded, setPromptExpanded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const scheduleDescription = data
    ? humanReadableScheduleFromCron(data.editor_mode, data.cron_expression)
    : undefined;

  const handleBack = useCallback(() => {
    router.push(TASKS_PATH);
  }, [router]);

  const handleToggleStatus = useCallback(async () => {
    if (!data) return;
    const next: ScheduledTaskStatus =
      data.status === "ACTIVE" ? "PAUSED" : "ACTIVE";
    setBusy(true);
    try {
      const updated = await updateScheduledTask(data.id, { status: next });
      await mutate(updated, { revalidate: false });
      toast.success(
        next === "ACTIVE" ? t("toasts.resumed") : t("toasts.paused")
      );
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("toasts.statusUpdateFailed")
      );
    } finally {
      setBusy(false);
    }
  }, [data, mutate, t]);

  const handleRunNow = useCallback(async () => {
    if (!data) return;
    setBusy(true);
    try {
      await runScheduledTaskNow(data.id);
      toast.success(t("toasts.runQueued", { name: data.name }));
      void mutate();
      // The run history table owns paginated SWR keys under this prefix —
      // invalidate every variant so the new ``manual_run_now`` row appears.
      const runsPrefix = SWR_KEYS.scheduledTaskRuns(data.id);
      void globalMutate(
        (key) => typeof key === "string" && key.startsWith(runsPrefix)
      );
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("toasts.runStartFailed")
      );
    } finally {
      setBusy(false);
    }
  }, [data, mutate, globalMutate, t]);

  const handleDelete = useCallback(async () => {
    if (!data) return;
    setBusy(true);
    try {
      await deleteScheduledTask(data.id);
      toast.success(t("toasts.deleted", { name: data.name }));
      await globalMutate<ScheduledTaskListResponse>(
        SWR_KEYS.scheduledTasks,
        (current) =>
          current && {
            ...current,
            items: current.items.filter((task) => task.id !== data.id),
          },
        { revalidate: false }
      );
      setConfirmDelete(false);
      router.replace(TASKS_PATH);
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("toasts.deleteFailed")
      );
      setBusy(false);
    }
  }, [data, globalMutate, router, t]);

  if (!taskId) {
    return (
      <Section gap={0} className="min-w-0 flex-1">
        <SettingsLayouts.Root width="lg">
          <SettingsLayouts.Header
            icon={SvgClock}
            title={t("fallbackTitle")}
            cancel={handleBack}
          />
          <SettingsLayouts.Body>
            <Text font="main-ui-body" color="text-03">
              {t("missingTaskId")}
            </Text>
          </SettingsLayouts.Body>
        </SettingsLayouts.Root>
      </Section>
    );
  }

  return (
    <Section gap={0} className="min-w-0 flex-1">
      <SettingsLayouts.Root width="lg">
        <SettingsLayouts.Header
          title={data?.name ?? t("fallbackTitle")}
          description={scheduleDescription}
          descriptionTag={data ? taskStatusTag(data.status) : undefined}
          stackActionsOnMobile
          actions={
            data
              ? [
                  <Button
                    key="edit"
                    icon={SvgEdit}
                    prominence="tertiary"
                    href={taskEditPath(data.id)}
                    disabled={busy}
                  >
                    {t("editButton")}
                  </Button>,
                  <Button
                    key="run"
                    icon={SvgZap}
                    prominence="tertiary"
                    onClick={() => void handleRunNow()}
                    disabled={busy}
                    data-testid="run-now-button"
                  >
                    {t("runNowButton")}
                  </Button>,
                  <Button
                    key="toggle"
                    icon={
                      data.status === "ACTIVE" ? SvgPauseCircle : SvgPlayCircle
                    }
                    prominence="primary"
                    onClick={() => void handleToggleStatus()}
                    disabled={busy}
                    data-testid="status-toggle"
                  >
                    {t(
                      data.status === "ACTIVE" ? "pauseButton" : "resumeButton"
                    )}
                  </Button>,
                  <Button
                    key="delete"
                    icon={SvgTrash}
                    prominence="tertiary"
                    onClick={() => setConfirmDelete(true)}
                    disabled={busy}
                    data-testid="delete-button"
                    aria-label={t("deleteButton")}
                    tooltip={t("deleteButton")}
                  />,
                ]
              : []
          }
        />
        <SettingsLayouts.Body>
          {isLoading ? (
            <Section height="auto" padding={12}>
              <IconLoader className="h-6 w-6" />
            </Section>
          ) : error || !data ? (
            <Text font="main-ui-body" color="text-03">
              {t("loadFailed")}
            </Text>
          ) : (
            <Section height="auto" alignItems="stretch" gap={8}>
              <Card
                padding={4}
                color="background-tint-01"
                border="solid"
                rounding={4}
              >
                <Section height="auto" alignItems="stretch" gap={2}>
                  <Section
                    height="auto"
                    flexDirection="row"
                    justifyContent="between"
                    gap={2}
                  >
                    <Text font="secondary-action" color="text-03">
                      {tTasks("form.fields.prompt.label")}
                    </Text>
                    <Button
                      icon={promptExpanded ? SvgChevronUp : SvgChevronDown}
                      size="sm"
                      prominence="tertiary"
                      aria-label={tTasks("form.fields.prompt.label")}
                      aria-expanded={promptExpanded}
                      aria-controls="task-prompt"
                      onClick={() => setPromptExpanded((expanded) => !expanded)}
                    />
                  </Section>
                  <div id="task-prompt" className="whitespace-pre-wrap">
                    <Text
                      font="main-ui-mono"
                      wordWrap="wrap-anywhere"
                      maxLines={promptExpanded ? undefined : 2}
                    >
                      {promptExpanded
                        ? data.prompt
                        : data.prompt.replace(/\s+/g, " ").trim()}
                    </Text>
                  </div>
                </Section>
                <div className="mt-4 border-t border-border-01 pt-4">
                  <TaskActionPoliciesSummary taskId={data.id} />
                </div>
              </Card>
              <Section height="auto" alignItems="stretch" gap={4}>
                <Text as="h2" font="main-content-emphasis">
                  {t("runHistoryTab")}
                </Text>
                <RunHistoryTable taskId={data.id} />
              </Section>
            </Section>
          )}
        </SettingsLayouts.Body>

        {confirmDelete && data && (
          <ConfirmationModalLayout
            icon={SvgTrash}
            title={t("confirmDelete.title", { name: data.name })}
            description={t("confirmDelete.description")}
            onClose={() => setConfirmDelete(false)}
            submit={
              <Button
                variant="danger"
                prominence="primary"
                onClick={() => void handleDelete()}
                disabled={busy}
                data-testid="confirm-delete-task"
              >
                {busy
                  ? t("confirmDelete.deletingButton")
                  : t("confirmDelete.deleteButton")}
              </Button>
            }
          />
        )}
      </SettingsLayouts.Root>
    </Section>
  );
}
