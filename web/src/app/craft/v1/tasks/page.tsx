"use client";

import { useCallback, useMemo, useState } from "react";
import useSWR from "swr";
import { useRouter } from "next/navigation";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { Section } from "@/layouts/general-layouts";
import Card from "@/refresh-components/cards/Card";
import Text from "@/refresh-components/texts/Text";
import { Button, Tooltip } from "@opal/components";
import { toast } from "@/hooks/useToast";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import {
  SvgClock,
  SvgEdit,
  SvgPauseCircle,
  SvgPlayCircle,
  SvgPlus,
  SvgRefreshCw,
  SvgTrash,
} from "@opal/icons";
import {
  deleteScheduledTask,
  listScheduledTasks,
  runScheduledTaskNow,
  updateScheduledTask,
} from "@/app/craft/v1/tasks/api";
import {
  RunStatusBadge,
  TaskStatusBadge,
} from "@/app/craft/v1/tasks/components/StatusBadge";
import {
  NEW_TASK_PATH,
  STARTER_PROMPTS,
  taskDetailPath,
  taskEditPath,
} from "@/app/craft/v1/tasks/constants";
import type {
  ScheduledTaskListItem,
  ScheduledTaskStatus,
} from "@/app/craft/v1/tasks/interfaces";
import {
  formatAbsolute,
  formatRelativeShort,
} from "@/app/craft/v1/tasks/utils";

const SWR_KEY = ["scheduled-tasks-list"];

export default function ScheduledTasksListPage() {
  const router = useRouter();
  const { data, error, isLoading, mutate } = useSWR<ScheduledTaskListItem[]>(
    SWR_KEY,
    () => listScheduledTasks(),
    { revalidateOnFocus: false }
  );
  const [pendingDelete, setPendingDelete] =
    useState<ScheduledTaskListItem | null>(null);
  const [busyTaskId, setBusyTaskId] = useState<string | null>(null);

  const refresh = useCallback(() => {
    void mutate();
  }, [mutate]);

  const handleRunNow = useCallback(
    async (task: ScheduledTaskListItem) => {
      setBusyTaskId(task.id);
      try {
        await runScheduledTaskNow(task.id);
        toast.success(`Queued run for "${task.name}".`);
        refresh();
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "Failed to start run");
      } finally {
        setBusyTaskId(null);
      }
    },
    [refresh]
  );

  const handleToggleStatus = useCallback(
    async (task: ScheduledTaskListItem) => {
      const next: ScheduledTaskStatus =
        task.status === "active" ? "paused" : "active";
      setBusyTaskId(task.id);
      try {
        await updateScheduledTask(task.id, { status: next });
        toast.success(next === "active" ? "Task resumed." : "Task paused.");
        refresh();
      } catch (err) {
        toast.error(
          err instanceof Error ? err.message : "Failed to update status"
        );
      } finally {
        setBusyTaskId(null);
      }
    },
    [refresh]
  );

  const handleDelete = useCallback(async () => {
    if (!pendingDelete) return;
    setBusyTaskId(pendingDelete.id);
    try {
      await deleteScheduledTask(pendingDelete.id);
      toast.success(`Deleted "${pendingDelete.name}".`);
      setPendingDelete(null);
      refresh();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete task");
    } finally {
      setBusyTaskId(null);
    }
  }, [pendingDelete, refresh]);

  const headerActions = useMemo(
    () => (
      <Button
        variant="default"
        prominence="primary"
        icon={SvgPlus}
        href={NEW_TASK_PATH}
        data-testid="new-task-button"
      >
        New scheduled task
      </Button>
    ),
    []
  );

  return (
    <SettingsLayouts.Root width="lg">
      <SettingsLayouts.Header
        icon={SvgClock}
        title="Scheduled Tasks"
        description="Run Craft prompts on a timer. Each fire creates a fresh session that runs in the background."
        rightChildren={headerActions}
      />
      <SettingsLayouts.Body>
        {isLoading ? (
          <div className="flex justify-center py-12">
            <SimpleLoader className="h-6 w-6" />
          </div>
        ) : error ? (
          <Section gap={0.5}>
            <Text mainUiBody text03>
              Failed to load scheduled tasks.
            </Text>
            <Button
              variant="default"
              prominence="secondary"
              icon={SvgRefreshCw}
              onClick={refresh}
            >
              Try again
            </Button>
          </Section>
        ) : !data || data.length === 0 ? (
          <EmptyState
            onSelectStarter={(prompt) => {
              const params = new URLSearchParams({
                starter: prompt.title,
                prompt: prompt.prompt,
                mode: prompt.mode,
                payload: JSON.stringify(prompt.payload),
              });
              router.push(`${NEW_TASK_PATH}?${params.toString()}`);
            }}
          />
        ) : (
          <Section gap={0.5}>
            {/* Table header */}
            <div className="grid grid-cols-[2fr_1.5fr_0.8fr_1.4fr_1.4fr_auto] gap-3 px-3 py-2 border-b border-border-01">
              <Text figureSmallLabel text03>
                Name
              </Text>
              <Text figureSmallLabel text03>
                Schedule
              </Text>
              <Text figureSmallLabel text03>
                Status
              </Text>
              <Text figureSmallLabel text03>
                Last run
              </Text>
              <Text figureSmallLabel text03>
                Next run
              </Text>
              <Text figureSmallLabel text03>
                Actions
              </Text>
            </div>
            {data.map((task) => (
              <TaskRow
                key={task.id}
                task={task}
                disabled={busyTaskId === task.id}
                onRunNow={() => void handleRunNow(task)}
                onToggleStatus={() => void handleToggleStatus(task)}
                onEdit={() => router.push(taskEditPath(task.id))}
                onDelete={() => setPendingDelete(task)}
                onOpen={() => router.push(taskDetailPath(task.id))}
              />
            ))}
          </Section>
        )}
      </SettingsLayouts.Body>

      {pendingDelete && (
        <ConfirmationModalLayout
          icon={SvgTrash}
          title={`Delete "${pendingDelete.name}"?`}
          description="This stops future runs and removes the task. Past run history (and the underlying sessions) will be preserved for audit."
          onClose={() => setPendingDelete(null)}
          submit={
            <Button
              variant="danger"
              prominence="primary"
              onClick={() => void handleDelete()}
              disabled={busyTaskId === pendingDelete.id}
              data-testid="confirm-delete-task"
            >
              {busyTaskId === pendingDelete.id ? "Deleting..." : "Delete"}
            </Button>
          }
        />
      )}
    </SettingsLayouts.Root>
  );
}

// ---------------------------------------------------------------------------
// Row
// ---------------------------------------------------------------------------

interface TaskRowProps {
  task: ScheduledTaskListItem;
  disabled: boolean;
  onRunNow: () => void;
  onToggleStatus: () => void;
  onEdit: () => void;
  onDelete: () => void;
  onOpen: () => void;
}

function TaskRow({
  task,
  disabled,
  onRunNow,
  onToggleStatus,
  onEdit,
  onDelete,
  onOpen,
}: TaskRowProps) {
  return (
    <div
      className="grid grid-cols-[2fr_1.5fr_0.8fr_1.4fr_1.4fr_auto] gap-3 px-3 py-3 rounded-08 border border-transparent hover:bg-background-tint-01 hover:border-border-02 cursor-pointer items-center"
      data-testid={`task-row-${task.id}`}
      onClick={onOpen}
    >
      <Text mainUiBody text05 className="truncate">
        {task.name}
      </Text>
      <Text mainUiBody text03 className="truncate">
        {task.human_readable_schedule}
      </Text>
      <div>
        <TaskStatusBadge status={task.status} />
      </div>
      <div className="flex flex-col">
        {task.last_run ? (
          <>
            <RunStatusBadge status={task.last_run.status} />
            <Text secondaryBody text03>
              {formatRelativeShort(task.last_run.started_at)}
            </Text>
          </>
        ) : (
          <Text mainUiBody text03>
            —
          </Text>
        )}
      </div>
      <Tooltip
        tooltip={
          task.next_run_at ? formatAbsolute(task.next_run_at) : undefined
        }
        side="top"
      >
        <Text mainUiBody text03>
          {task.next_run_at ? formatRelativeShort(task.next_run_at) : "—"}
        </Text>
      </Tooltip>
      <div
        className="flex items-center gap-1"
        onClick={(e) => e.stopPropagation()}
      >
        <Tooltip tooltip="Run now" side="top">
          <Button
            icon={SvgPlayCircle}
            variant="default"
            prominence="tertiary"
            size="sm"
            onClick={onRunNow}
            disabled={disabled}
            data-testid={`row-run-now-${task.id}`}
          />
        </Tooltip>
        <Tooltip
          tooltip={task.status === "active" ? "Pause" : "Resume"}
          side="top"
        >
          <Button
            icon={task.status === "active" ? SvgPauseCircle : SvgPlayCircle}
            variant="default"
            prominence="tertiary"
            size="sm"
            onClick={onToggleStatus}
            disabled={disabled}
            data-testid={`row-toggle-${task.id}`}
          />
        </Tooltip>
        <Tooltip tooltip="Edit" side="top">
          <Button
            icon={SvgEdit}
            variant="default"
            prominence="tertiary"
            size="sm"
            onClick={onEdit}
            disabled={disabled}
            data-testid={`row-edit-${task.id}`}
          />
        </Tooltip>
        <Tooltip tooltip="Delete" side="top">
          <Button
            icon={SvgTrash}
            variant="danger"
            prominence="tertiary"
            size="sm"
            onClick={onDelete}
            disabled={disabled}
            data-testid={`row-delete-${task.id}`}
          />
        </Tooltip>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------

interface EmptyStateProps {
  onSelectStarter: (prompt: (typeof STARTER_PROMPTS)[number]) => void;
}

function EmptyState({ onSelectStarter }: EmptyStateProps) {
  return (
    <Section gap={1}>
      <div className="flex flex-col items-center text-center py-6 gap-2">
        <SvgClock size={48} className="text-text-03" />
        <Text headingH2 text05>
          Hand Craft a recurring job
        </Text>
        <Text mainUiBody text03 className="max-w-xl">
          Save a prompt + schedule and Craft will run it on a timer. Each fire
          creates a fresh session you can open from this page.
        </Text>
        <div className="pt-2">
          <Button
            variant="default"
            prominence="primary"
            icon={SvgPlus}
            href={NEW_TASK_PATH}
          >
            Create scheduled task
          </Button>
        </div>
      </div>
      <Text mainUiAction text05>
        Or start from a template:
      </Text>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {STARTER_PROMPTS.map((starter) => (
          <button
            key={starter.title}
            type="button"
            onClick={() => onSelectStarter(starter)}
            className="text-left"
            data-testid={`starter-${starter.title}`}
          >
            <Card>
              <Text mainUiAction text05>
                {starter.title}
              </Text>
              <Text secondaryBody text03>
                {starter.prompt}
              </Text>
            </Card>
          </button>
        ))}
      </div>
    </Section>
  );
}
