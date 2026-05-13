"use client";

import { useCallback, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import useSWR, { useSWRConfig } from "swr";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import Text from "@/refresh-components/texts/Text";
import { Button } from "@opal/components";
import { toast } from "@/hooks/useToast";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
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
import RunHistoryTable from "@/app/craft/v1/tasks/components/RunHistoryTable";
import { TaskStatusBadge } from "@/app/craft/v1/tasks/components/StatusBadge";
import { TASKS_PATH, taskEditPath } from "@/app/craft/v1/tasks/constants";
import type {
  ScheduledTaskDetail,
  ScheduledTaskStatus,
} from "@/app/craft/v1/tasks/interfaces";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";

export default function ScheduledTaskDetailPage() {
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
      toast.success(next === "ACTIVE" ? "Task resumed." : "Task paused.");
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to update status"
      );
    } finally {
      setBusy(false);
    }
  }, [data, mutate]);

  const handleRunNow = useCallback(async () => {
    if (!data) return;
    setBusy(true);
    try {
      await runScheduledTaskNow(data.id);
      toast.success(`Queued run for "${data.name}".`);
      void mutate();
      // The run history table owns paginated SWR keys under this prefix —
      // invalidate every variant so the new ``manual_run_now`` row appears.
      const runsPrefix = SWR_KEYS.scheduledTaskRuns(data.id);
      void globalMutate(
        (key) => typeof key === "string" && key.startsWith(runsPrefix)
      );
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to start run");
    } finally {
      setBusy(false);
    }
  }, [data, mutate, globalMutate]);

  const handleDelete = useCallback(async () => {
    if (!data) return;
    setBusy(true);
    try {
      await deleteScheduledTask(data.id);
      toast.success(`Deleted "${data.name}".`);
      router.push(TASKS_PATH);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete task");
      setBusy(false);
    }
  }, [data, router]);

  if (!taskId) {
    return (
      <SettingsLayouts.Root width="lg">
        <SettingsLayouts.Header
          icon={SvgClock}
          title="Scheduled task"
          backButton
          onBack={handleBack}
        />
        <SettingsLayouts.Body>
          <Text mainUiBody text03>
            Missing task id.
          </Text>
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    );
  }

  return (
    <SettingsLayouts.Root width="lg">
      <SettingsLayouts.Header
        icon={SvgClock}
        title={data?.name ?? "Scheduled task"}
        description={data?.human_readable_schedule}
        backButton
        onBack={handleBack}
        rightChildren={
          data ? (
            <div className="flex items-center gap-2">
              <TaskStatusBadge status={data.status} />
              <Button
                icon={SvgPlayCircle}
                variant="default"
                prominence="secondary"
                onClick={() => void handleRunNow()}
                disabled={busy}
                data-testid="run-now-button"
              >
                Run now
              </Button>
              <Button
                icon={data.status === "ACTIVE" ? SvgPauseCircle : SvgPlayCircle}
                variant="default"
                prominence="secondary"
                onClick={() => void handleToggleStatus()}
                disabled={busy}
                data-testid="status-toggle"
              >
                {data.status === "ACTIVE" ? "Pause" : "Resume"}
              </Button>
              <Button
                icon={SvgEdit}
                variant="default"
                prominence="secondary"
                href={taskEditPath(data.id)}
                disabled={busy}
              >
                Edit
              </Button>
              <Button
                icon={SvgTrash}
                variant="danger"
                prominence="secondary"
                onClick={() => setConfirmDelete(true)}
                disabled={busy}
                data-testid="delete-button"
              >
                Delete
              </Button>
            </div>
          ) : undefined
        }
      />
      <SettingsLayouts.Body>
        {isLoading ? (
          <div className="flex justify-center py-12">
            <SimpleLoader className="h-6 w-6" />
          </div>
        ) : error || !data ? (
          <Text mainUiBody text03>
            Failed to load scheduled task.
          </Text>
        ) : (
          <RunHistoryTable taskId={data.id} />
        )}
      </SettingsLayouts.Body>

      {confirmDelete && data && (
        <ConfirmationModalLayout
          icon={SvgTrash}
          title={`Delete "${data.name}"?`}
          description="This stops future runs and removes the task. Past run history (and the underlying sessions) will be preserved for audit."
          onClose={() => setConfirmDelete(false)}
          submit={
            <Button
              variant="danger"
              prominence="primary"
              onClick={() => void handleDelete()}
              disabled={busy}
              data-testid="confirm-delete-task"
            >
              {busy ? "Deleting..." : "Delete"}
            </Button>
          }
        />
      )}
    </SettingsLayouts.Root>
  );
}
