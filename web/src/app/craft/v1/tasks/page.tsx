"use client";

import { useCallback, useMemo, useState } from "react";
import useSWR from "swr";
import { useRouter } from "next/navigation";
import { SettingsLayouts } from "@opal/layouts";
import { Section } from "@/layouts/general-layouts";
import {
  Button,
  Table,
  Text,
  Tooltip,
  createTableColumns,
} from "@opal/components";
import { IllustrationContent } from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";
import { toast } from "@/hooks/useToast";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import {
  SvgClock,
  SvgPlus,
  SvgRefreshCw,
  SvgTrash,
  SvgSimpleLoader,
} from "@opal/icons";
import { deleteScheduledTask } from "@/app/craft/v1/tasks/api";
import {
  RunStatusBadge,
  TaskStatusBadge,
} from "@/app/craft/v1/tasks/components/StatusBadge";
import {
  NEW_TASK_PATH,
  TASKS_PAGE_SIZE,
  taskDetailPath,
} from "@/app/craft/v1/tasks/constants";
import type {
  ScheduledTaskListItem,
  ScheduledTaskListResponse,
} from "@/app/craft/v1/tasks/interfaces";
import {
  formatAbsolute,
  formatRelativeShort,
} from "@/app/craft/v1/tasks/utils";
import { humanReadableScheduleFromCron } from "@/app/craft/v1/tasks/schedule";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";

const tc = createTableColumns<ScheduledTaskListItem>();

interface RowActionHandlers {
  busyTaskId: string | null;
  onDelete: (task: ScheduledTaskListItem) => void;
}

function buildColumns(handlers: RowActionHandlers) {
  return [
    tc.column("name", {
      header: "Name",
      weight: 25,
      enableSorting: false,
      cell: (value) => (
        <Text font="main-ui-body" color="text-05" nowrap>
          {value}
        </Text>
      ),
    }),
    tc.column("human_readable_schedule", {
      header: "Schedule",
      weight: 22,
      enableSorting: false,
      cell: (value) => (
        <Text font="main-ui-body" color="text-03" nowrap>
          {value}
        </Text>
      ),
    }),
    tc.column("status", {
      header: "Status",
      weight: 12,
      enableSorting: false,
      cell: (status) => <TaskStatusBadge status={status} />,
    }),
    tc.column("last_run", {
      header: "Last run",
      weight: 18,
      enableSorting: false,
      cell: (lastRun) => {
        if (!lastRun) {
          return (
            <Text font="main-ui-body" color="text-03">
              —
            </Text>
          );
        }
        return (
          <div className="flex flex-col gap-0.5">
            <RunStatusBadge status={lastRun.status} />
            <Text font="secondary-body" color="text-03">
              {formatRelativeShort(lastRun.started_at)}
            </Text>
          </div>
        );
      },
    }),
    tc.column("next_run_at", {
      header: "Next run",
      weight: 13,
      enableSorting: false,
      cell: (nextRunAt) => {
        if (!nextRunAt) {
          return (
            <Text font="main-ui-body" color="text-03">
              —
            </Text>
          );
        }
        return (
          <Tooltip tooltip={formatAbsolute(nextRunAt)} side="top">
            <Text font="main-ui-body" color="text-03" nowrap>
              {formatRelativeShort(nextRunAt)}
            </Text>
          </Tooltip>
        );
      },
    }),
    tc.actions({
      showColumnVisibility: false,
      showSorting: false,
      cell: (task) => <TaskRowActions task={task} handlers={handlers} />,
    }),
  ];
}

export default function ScheduledTasksListPage() {
  const router = useRouter();
  const { data, error, isLoading, mutate } = useSWR<ScheduledTaskListResponse>(
    SWR_KEYS.scheduledTasks,
    errorHandlingFetcher,
    { revalidateOnFocus: false }
  );
  const tasks = useMemo<ScheduledTaskListItem[]>(
    () =>
      data?.items.map((task) => ({
        ...task,
        human_readable_schedule: humanReadableScheduleFromCron(
          task.editor_mode,
          task.cron_expression
        ),
      })) ?? [],
    [data?.items]
  );
  const [pendingDelete, setPendingDelete] =
    useState<ScheduledTaskListItem | null>(null);
  const [busyTaskId, setBusyTaskId] = useState<string | null>(null);

  const refresh = useCallback(() => {
    void mutate();
  }, [mutate]);

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

  const columns = useMemo(
    () =>
      buildColumns({
        busyTaskId,
        onDelete: (task) => setPendingDelete(task),
      }),
    [busyTaskId]
  );

  const headerActions = useMemo(
    () => (
      <Button
        variant="default"
        prominence="primary"
        icon={SvgPlus}
        href={NEW_TASK_PATH}
        data-testid="new-task-button"
      >
        New Scheduled Task
      </Button>
    ),
    []
  );

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgClock}
        title="Scheduled Tasks"
        description="Run Craft prompts on a timer. Each fire creates a fresh session that runs in the background."
        rightChildren={headerActions}
      />
      <SettingsLayouts.Body>
        {isLoading ? (
          <div className="flex justify-center py-12">
            <SvgSimpleLoader className="h-6 w-6" />
          </div>
        ) : error ? (
          <Section gap={0.5}>
            <Text font="main-ui-body" color="text-03">
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
        ) : (
          <Table
            data={tasks}
            columns={columns}
            getRowId={(row) => row.id}
            pageSize={
              tasks.length > 0 ? Math.min(tasks.length, TASKS_PAGE_SIZE) : 1
            }
            selectionBehavior="single-select"
            onRowClick={(row) => router.push(taskDetailPath(row.id))}
            emptyState={
              <IllustrationContent
                illustration={SvgNoResult}
                title="No scheduled tasks found"
                description="No scheduled tasks have been created yet."
              />
            }
          />
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
// Row actions
// ---------------------------------------------------------------------------

interface TaskRowActionsProps {
  task: ScheduledTaskListItem;
  handlers: RowActionHandlers;
}

function TaskRowActions({ task, handlers }: TaskRowActionsProps) {
  const disabled = handlers.busyTaskId === task.id;
  return (
    <div className="flex items-center gap-0.5">
      <Tooltip tooltip="Delete" side="top">
        <Button
          icon={SvgTrash}
          variant="danger"
          prominence="tertiary"
          size="sm"
          onClick={() => handlers.onDelete(task)}
          disabled={disabled}
          data-testid={`row-delete-${task.id}`}
        />
      </Tooltip>
    </div>
  );
}
