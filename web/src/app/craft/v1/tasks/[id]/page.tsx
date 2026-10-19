"use client";

import { IconLoader } from "@opal/loaders";
import { useCallback, useState } from "react";
import { useTranslations } from "next-intl";
import { useParams, useRouter } from "next/navigation";
import useSWR, { useSWRConfig } from "swr";
import { SettingsLayouts, toast } from "@opal/layouts";
import { Button, Text } from "@opal/components";
import { ConfirmationModalLayout } from "@opal/layouts";
import {
  SvgClock,
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
import { TaskActionPoliciesSummary } from "@/app/craft/v1/tasks/components/TaskActionPolicies";
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
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const taskId = params?.id;

  const { data, error, isLoading, mutate } = useSWR<ScheduledTaskDetail>(
    taskId ? SWR_KEYS.scheduledTask(taskId) : null,
    errorHandlingFetcher,
    { revalidateOnFocus: false }
  );

  const { mutate: globalMutate } = useSWRConfig();

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
    );
  }

  return (
    <SettingsLayouts.Root width="lg">
      <SettingsLayouts.Header
        icon={SvgClock}
        title={data?.name ?? t("fallbackTitle")}
        description={scheduleDescription}
        descriptionTag={data ? taskStatusTag(data.status) : undefined}
        cancel={handleBack}
        actions={
          data
            ? [
                <Button
                  key="run"
                  icon={SvgPlayCircle}
                  variant="default"
                  prominence="secondary"
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
                  variant="default"
                  prominence="secondary"
                  onClick={() => void handleToggleStatus()}
                  disabled={busy}
                  data-testid="status-toggle"
                >
                  {data.status === "ACTIVE"
                    ? t("pauseButton")
                    : t("resumeButton")}
                </Button>,
                <Button
                  key="edit"
                  icon={SvgEdit}
                  variant="default"
                  prominence="secondary"
                  href={taskEditPath(data.id)}
                  disabled={busy}
                >
                  {t("editButton")}
                </Button>,
                <Button
                  key="delete"
                  icon={SvgTrash}
                  variant="danger"
                  prominence="secondary"
                  onClick={() => setConfirmDelete(true)}
                  disabled={busy}
                  data-testid="delete-button"
                >
                  {t("deleteButton")}
                </Button>,
              ]
            : []
        }
      />
      <SettingsLayouts.Body>
        {isLoading ? (
          <div className="flex justify-center py-12">
            <IconLoader className="h-6 w-6" />
          </div>
        ) : error || !data ? (
          <Text font="main-ui-body" color="text-03">
            {t("loadFailed")}
          </Text>
        ) : (
          <div className="flex flex-col gap-6">
            <TaskActionPoliciesSummary taskId={data.id} />
            <RunHistoryTable taskId={data.id} />
          </div>
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
  );
}
