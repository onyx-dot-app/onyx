"use client";

import { useCallback, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import useSWR from "swr";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { Section } from "@/layouts/general-layouts";
import Card from "@/refresh-components/cards/Card";
import Text from "@/refresh-components/texts/Text";
import { Button, Divider, Tooltip } from "@opal/components";
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
  getScheduledTask,
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
import {
  formatAbsolute,
  formatRelativeShort,
} from "@/app/craft/v1/tasks/utils";

export default function ScheduledTaskDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const taskId = params?.id;

  const { data, error, isLoading, mutate } = useSWR<ScheduledTaskDetail>(
    taskId ? ["scheduled-task", taskId] : null,
    () => getScheduledTask(taskId as string),
    { revalidateOnFocus: false }
  );

  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const handleBack = useCallback(() => {
    router.push(TASKS_PATH);
  }, [router]);

  const handleToggleStatus = useCallback(async () => {
    if (!data) return;
    const next: ScheduledTaskStatus =
      data.status === "active" ? "paused" : "active";
    setBusy(true);
    try {
      await updateScheduledTask(data.id, { status: next });
      toast.success(next === "active" ? "Task resumed." : "Task paused.");
      void mutate();
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
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to start run");
    } finally {
      setBusy(false);
    }
  }, [data, mutate]);

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
                icon={data.status === "active" ? SvgPauseCircle : SvgPlayCircle}
                variant="default"
                prominence="secondary"
                onClick={() => void handleToggleStatus()}
                disabled={busy}
                data-testid="status-toggle"
              >
                {data.status === "active" ? "Pause" : "Resume"}
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
          <Section gap={1}>
            <Card>
              <div className="flex items-center gap-2">
                <TaskStatusBadge status={data.status} />
                <Text mainUiBody text03>
                  {data.timezone}
                </Text>
              </div>
              <Divider />
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                <div>
                  <Text figureSmallLabel text03>
                    Next run
                  </Text>
                  <Tooltip
                    tooltip={
                      data.next_run_at
                        ? formatAbsolute(data.next_run_at)
                        : undefined
                    }
                    side="top"
                  >
                    <Text mainUiBody text05>
                      {data.next_run_at
                        ? formatRelativeShort(data.next_run_at)
                        : "—"}
                    </Text>
                  </Tooltip>
                </div>
                <div>
                  <Text figureSmallLabel text03>
                    Last run
                  </Text>
                  <Text mainUiBody text05>
                    {data.last_run
                      ? formatRelativeShort(data.last_run.started_at)
                      : "—"}
                  </Text>
                </div>
              </div>
              <Divider />
              <Text figureSmallLabel text03>
                Prompt
              </Text>
              <pre className="whitespace-pre-wrap font-main-ui-body text-text-05 bg-background-tint-01 rounded-08 p-3">
                {data.prompt}
              </pre>
              {data.next_runs.length > 0 && (
                <>
                  <Divider />
                  <Text figureSmallLabel text03>
                    Upcoming
                  </Text>
                  <ul className="flex flex-col gap-1">
                    {data.next_runs.map((iso, i) => (
                      <li key={iso}>
                        <Text mainUiBody text05>
                          {i + 1}. {formatAbsolute(iso)}
                        </Text>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </Card>

            <Card>
              <Text mainUiAction text05>
                Run history
              </Text>
              <RunHistoryTable taskId={data.id} />
            </Card>
          </Section>
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
